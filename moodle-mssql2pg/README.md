# moodle-mssql2pg — Chuyển database Moodle từ SQL Server sang PostgreSQL

Công cụ tự động chuyển database **Moodle** từ SQL Server (sqlsrv) sang PostgreSQL (pgsql).
Bạn chỉ cần cấu hình **2 connection** rồi chạy **một lệnh**. Công cụ xử lý đúng các quy tắc
Moodle để **không phát sinh lỗi schema/XMLDB** khi chạy site trên PostgreSQL.

## Nó làm gì (pipeline 6 bước)

`discover → generate → migrate → fix → verify → report`

1. **discover** — tự quét SQL Server: danh sách bảng `mdl_*`, cột `char/nchar`, số dòng.
2. **generate** — sinh file cấu hình `pgloader` theo chuẩn Moodle.
3. **migrate** — chạy pgloader chuyển schema + dữ liệu (có resume nếu lỗi giữa chừng).
4. **fix** — vá hậu kỳ trên PostgreSQL: bỏ foreign key, trim khoảng trắng `char`, chuẩn hóa sequence, `VACUUM ANALYZE`.
5. **verify** — đối chiếu số dòng 2 bên, (tùy chọn) chạy `check_database_schema.php` của Moodle.
6. **report** — xuất `output/report.md` (PASS/FAIL từng bảng).

### Vì sao không phát sinh lỗi Moodle
- **Không tạo foreign key** — Moodle chỉ dùng index, không dùng FK constraint.
- **Ép kiểu đúng chuẩn Moodle** — `bit`/`tinyint` → `smallint` (không bao giờ `boolean`).
- **Chuẩn hóa sequence** cho cột `id` để insert không trùng khóa.
- **Trim khoảng trắng thừa** ở cột `char/nchar` (SQL Server pad khoảng trắng).

## 1. Yêu cầu
- **Docker** (khuyến nghị) — image đã đóng gói sẵn pgloader + FreeTDS + Python, khỏi cài đặt.
- Máy chạy tool phải **truy cập mạng được tới cả 2 database**.

## 2. Cấu hình
1. Copy file mẫu:
   ```bash
   cp config.example.yml config.yml
   ```
2. Mở `config.yml`, điền 2 khối `source_mssql` và `target_pgsql` (host, port, db, user, password).
3. (Tùy chọn) chỉnh `options`: `exclude_data_tables`, `batch_size`, `moodle_codebase_path`…

> Mật khẩu điền **nguyên bản**, không percent-encode: pgloader gửi thẳng chuỗi trong
> connection string tới server, viết `%40` là đăng nhập hỏng. Ký tự `@` và `/` thì
> pgloader không biểu diễn được — tool báo lỗi ngay, cần đổi sang tài khoản khác.
> Muốn không lưu mật khẩu trong file: đặt biến môi trường `MSSQL_PASSWORD` / `PGSQL_PASSWORD`.

## 3. Chạy
```bash
docker compose run --rm migrator test           # kiểm tra 2 kết nối
docker compose run --rm migrator run --dry-run  # xem trước các file .load (không nạp dữ liệu)
docker compose run --rm migrator run            # chạy thật
```
Kết quả: database PostgreSQL đã được chuyển + `output/report.md` (PASS/FAIL, số dòng từng bảng).

> Nếu database dùng IP nội bộ (vd `172.100.100.x`), mở `docker-compose.yml` và bỏ comment
> dòng `network_mode: host` (trên Linux) để container truy cập được.

## 4. Bảng loại trừ (quan trọng)
Các bảng trong `exclude_data_tables` (log, cache, session, temp…) vẫn được **tạo bảng RỖNG**
(giữ đầy đủ cấu trúc) nhưng **bỏ dữ liệu** — nên Moodle **không báo thiếu bảng**. Mặc định đã
loại `mdl_logstore_standard_log`, `mdl_log`, và các bảng transient khác (xem `config.example.yml`).

## 5. Runbook sau khi chuyển xong (để Moodle chạy KHÔNG lỗi)
Công cụ chỉ chuyển **database**. Để chạy site Moodle trên PostgreSQL:

1. Sửa `config.php` của Moodle:
   ```php
   $CFG->dbtype  = 'pgsql';
   $CFG->dbhost  = 'your_pg_host';
   $CFG->dbname  = 'your_pg_db';
   $CFG->dbuser  = 'your_pg_user';
   $CFG->dbpass  = 'your_pg_password';
   $CFG->prefix  = 'mdl_';
   $CFG->dboptions = array('dbport' => 5432);
   ```
2. **Copy `moodledata`** sang server mới (`rsync -a`). Database **KHÔNG** chứa nội dung file
   thật (ảnh, tài liệu upload) — Moodle lưu ở thư mục `moodledata/filedir`. **Bỏ qua bước này
   là ảnh/file sẽ hỏng** dù database đúng hoàn toàn. Đây là lỗi phổ biến nhất khi migrate.
3. Xóa cache:
   ```bash
   php admin/cli/purge_caches.php
   ```
4. Kiểm tra schema chuẩn Moodle (kỳ vọng "No differences found"):
   ```bash
   php admin/cli/check_database_schema.php
   ```
5. Test: đăng nhập, tạo thử 1 bản ghi (kiểm tra sequence hoạt động), chạy `php admin/cli/cron.php`.

## 6. Xử lý sự cố
- **`out of shared memory` / lock**: tăng `max_locks_per_transaction` (vd `128`) trên PostgreSQL
  rồi chạy lại `run` — nó tự **resume**, bỏ qua các batch đã xong.
- **Bảng lớn chạy lâu**: đã tự tách mỗi bảng lớn thành 1 file riêng; có thể tăng `large_table_threshold`.
- **pgloader lỗi ở một batch**: xem log chi tiết trong `output/<tên-file>.load.log`.
- **pgloader bản apt lỗi**: image Docker dùng bản của maintainer; nếu vẫn lỗi, build pgloader từ source.

## 7. Chạy không cần Docker (tùy chọn)
```bash
pip install ".[drivers]"     # cài pymssql + psycopg2 (cần FreeTDS trên máy)
moodle-mssql2pg run --config config.yml
```

## 8. Phát triển / chạy test
```bash
pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest tests/ -v
```

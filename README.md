# LMS_PTSC: SQL Server 2019 → PostgreSQL 18

Chuyển database Moodle `LMS_PTSC` từ SQL Server (202.143.111.14,2968) sang một
container PostgreSQL 18 chạy tại máy này.

## Kết nối tới database đích

| | |
|---|---|
| Container | `ptsc-pg18` (image `postgres:18`, PostgreSQL 18.6) |
| Host / port | `localhost:5518` |
| Database | `lms_ptsc` |
| User / password | `moodle` / `moodle` |
| Encoding | UTF8, collation `en_US.utf8` |
| Volume | named volume `ptsc-pg18_pg18data` (dữ liệu còn sau khi restart) |

```bash
psql -h localhost -p 5518 -U moodle -d lms_ptsc      # tu may host
docker exec -it ptsc-pg18 psql -U moodle -d lms_ptsc # tu trong container
```

## Cấu trúc

```
.
├── Makefile                # giao diện chính — chạy `make` để xem danh sách lệnh
├── RESTORE.md              # hướng dẫn restore file .sql lên server PostgreSQL khác
├── docker-compose.yml      # container PostgreSQL 18 (db) + tool migrate (migrator)
├── config.example.yml      # mẫu cấu hình — copy thành config.yml rồi điền
├── verify_deep.sh          # kiểm chứng độc lập sau khi migrate
├── moodle-mssql2pg/        # tool: discover → generate → migrate → fix → verify → report
│   └── Makefile            # lệnh phát triển tool (test, build, install)
└── docs/superpowers/       # spec và plan thiết kế của tool
```

`config.yml` và `output/` **không được commit** — chúng chứa mật khẩu thật
(file `.load` nhúng thẳng connection string vào nội dung).

## Chạy lần đầu

```bash
make config     # tao config.yml tu mau — mo ra dien host/user/password that
make all        # build -> test-conn -> migrate -> verify
```

Chạy `make` không tham số để xem toàn bộ lệnh. Các lệnh hay dùng:

| Lệnh | Việc |
|---|---|
| `make config` | Tạo `config.yml` từ mẫu |
| `make up` / `make down` | Bật / dừng container PostgreSQL 18 |
| `make test-conn` | Kiểm tra kết nối tới cả hai database |
| `make dry-run` | Sinh file `.load` để xem trước, không nạp dữ liệu |
| `make migrate` | Chạy migration đầy đủ |
| `make verify` | Đếm chính xác `COUNT(*)` cả hai phía |
| `make report` | Tóm tắt `output/report.md` |
| `make errors` | Tìm lỗi trong log pgloader |
| `make psql` | Mở `psql` vào database đích |
| `make dump` | Xuất file `.sql` ra `backup/` để restore lên server khác |
| `make dump-verify` | Restore lại file dump vào DB tạm để đối chiếu số dòng |
| `make test` | Chạy test suite của tool |
| `make clean` | Xoá `output/` |
| `make reset` | Xoá database đích + `output/` để chạy lại từ đầu — hỏi xác nhận |
| `make destroy` | Xoá container và volume — **mất toàn bộ dữ liệu**, hỏi xác nhận |

`reset` và `destroy` hỏi xác nhận trước khi xoá. Muốn bỏ qua khi viết script:
`make reset FORCE=1`.

> Mật khẩu trong `config.yml` điền **nguyên bản**, không percent-encode, và không
> được chứa `@` hoặc `/` — pgloader không biểu diễn được hai ký tự này (xem lỗi 2 bên dưới).

## Chạy lại từ đầu

```bash
make reset      # xoa database dich + output/
make migrate
```

> **Quan trọng**: phải xoá `output/migrate_state.json`. Tool dùng file này để resume và
> sẽ **bỏ qua** các batch đã đánh dấu xong, kể cả khi batch đó thực ra đã thất bại.

## Ba lỗi đã phải sửa để chạy được

1. **Base image không dùng được.** `dimitri/pgloader:latest` là Debian 11 (Python 3.9)
   trong khi tool yêu cầu Python ≥ 3.10, và apt keyring của nó đã hỏng.
   → `moodle-mssql2pg/Dockerfile` build từ `debian:bookworm-slim`: Python 3.11 + pgloader
   3.6.7~devel (đúng version pgloader mà image gốc đóng gói).

2. **Tool percent-encode mật khẩu, pgloader thì không decode.** pgloader gửi thẳng
   chuỗi trong connection string tới server, nên `%23` đến server vẫn là `%23`.
   → đã sửa `config.py` (`mssql_url`/`pgsql_url`) trong `moodle-mssql2pg` để giữ
   nguyên bản, và báo lỗi ngay nếu mật khẩu chứa `@` hoặc `/` — pgloader không có
   cách nào biểu diễn hai ký tự này.

3. **FreeTDS mặc định client charset ISO-8859-1.** Nguồn có collation
   `SQL_Latin1_General_CP1_CI_AS` (CP1252) và 1772 cột `nvarchar` chứa tiếng Việt.
   Để mặc định thì pgloader chết với `INVALID-UTF8-CONTINUATION-BYTE`, và nếu không
   chết thì tiếng Việt cũng hỏng.
   → `moodle-mssql2pg/Dockerfile` ép `client charset = UTF-8` và `tds version = 7.4`.

## Xuất file .sql để restore lên server khác

```bash
make dump          # tao backup/lms_ptsc.sql + ban tuong thich + ban .gz
make dump-verify   # restore lai vao DB tam de doi chieu so dong, roi xoa
```

Sinh ra hai bản, dữ liệu giống hệt nhau, chỉ khác vài dòng lệnh ở đầu file:

| Server đích | File |
|---|---|
| PostgreSQL 18 trở lên | `backup/lms_ptsc.sql` |
| PostgreSQL 13 → 17 | `backup/lms_ptsc-pg13-17.sql` |

Bản `pg13-17` bỏ `\restrict`/`\unrestrict` (lệnh của `psql` mới) và
`SET transaction_timeout` (tham số chỉ có từ PostgreSQL 17) — hai thứ làm server
cũ báo lỗi. Mỗi bản 175 MB, nén `.gz` còn 15 MB.

Các bước restore chi tiết: xem **[RESTORE.md](RESTORE.md)**.

## Lưu ý khi đọc `output/report.md`

Bước verify so số dòng nguồn lấy từ `sys.partitions` (số ước lượng, chụp lúc bắt đầu)
với `COUNT(*)` chính xác ở đích. Database nguồn đang chạy thật, nên các bảng ghi liên
tục (`mdl_task_log`, `mdl_logstore_standard_log`…) sẽ luôn báo `mismatch` dù bản sao
hoàn toàn đúng. Dùng `verify_deep.sh` để đếm chính xác cả hai phía trước khi kết luận.

## Bước tiếp theo nếu muốn chạy Moodle trên database này

Việc này **chưa làm** — mới chỉ chuyển database.

1. Sửa `config.php` của Moodle: `dbtype = 'pgsql'`, `dbhost`, `dbport => 5518`,
   `dbname = 'lms_ptsc'`, `dbuser/dbpass = moodle/moodle`, `prefix = 'mdl_'`.
2. **Copy `moodledata`** sang server mới. Database không chứa file thật (ảnh, tài liệu
   upload) — Moodle lưu ở `moodledata/filedir`. Bỏ bước này là ảnh/file hỏng hết dù
   database đúng hoàn toàn.
3. `php admin/cli/purge_caches.php`
4. `php admin/cli/check_database_schema.php` — kỳ vọng "No differences found".

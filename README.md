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
├── docker-compose.yml      # container PostgreSQL 18 (db) + tool migrate (migrator)
├── config.example.yml      # mẫu cấu hình — copy thành config.yml rồi điền
├── verify_deep.sh          # kiểm chứng độc lập sau khi migrate
├── moodle-mssql2pg/        # tool: discover → generate → migrate → fix → verify → report
└── docs/superpowers/       # spec và plan thiết kế của tool
```

`config.yml` và `output/` **không được commit** — chúng chứa mật khẩu thật
(file `.load` nhúng thẳng connection string vào nội dung).

## Chạy lần đầu

```bash
cp config.example.yml config.yml     # roi dien host/user/password that
docker compose up -d db              # bat PostgreSQL 18
docker compose build migrator        # build tool
docker compose run --rm migrator test    # kiem tra 2 ket noi
docker compose run --rm migrator run     # chay that
bash verify_deep.sh                      # kiem chung doc lap
```

> Mật khẩu trong `config.yml` điền **nguyên bản**, không percent-encode, và không
> được chứa `@` hoặc `/` — pgloader không biểu diễn được hai ký tự này (xem lỗi 2 bên dưới).

## Chạy lại

Chạy lại từ đầu (xoá sạch dữ liệu đích):

```bash
docker exec ptsc-pg18 psql -U moodle -d postgres \
  -c "DROP DATABASE IF EXISTS lms_ptsc WITH (FORCE);" -c "CREATE DATABASE lms_ptsc OWNER moodle;"
rm -f output/*.load output/*.log output/migrate_state.json output/discovered.json output/report.md
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

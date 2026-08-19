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
├── check_moodle_schema.sh  # chạy check_database_schema.php của Moodle lên DB đích
├── fix_moodle_indexes.sh   # (tuỳ chọn) tạo các index Moodle mong đợi mà nguồn thiếu
├── run_moodle_test.sh      # dựng một Moodle thật trỏ vào DB này để chạy thử
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

## Ba lỗi pgloader làm hỏng schema (Moodle không chạy được)

pgloader **bỏ typemod** khi tạo bảng, và PostgreSQL **cắt tên identifier ở 63 ký tự**.
Cả ba hậu quả dưới đây đều được vá trong bước `fix` của tool.

1. **`nvarchar(100)` → `text`** (1143 cột / 465 bảng). Moodle đọc metadata cột:
   `text` → meta_type `X` (clob), và `moodle_database->where_clause()` từ chối **mọi**
   điều kiện so sánh bằng trên cột đó. Site chết ngay khi khởi động:

   ```
   Comparisons of text column conditions are not allowed.
   Please use sql_compare_text() in your query.
   Error code: textconditionsnotallowed
     line 204 of /lib/classes/plugin_manager.php: call to moodle_database->get_records()
   ```

   → `fix` chạy `ALTER COLUMN ... TYPE varchar(n)` theo đúng độ dài bên MSSQL.

2. **`decimal(10,5)` → `numeric` không precision** (121 cột, gồm các cột điểm như
   `mdl_grade_grades.finalgrade`). Moodle báo `size is (-1,65531), expected (10,5)`.
   → cùng cơ chế, `ALTER COLUMN ... TYPE numeric(p,s)`.

3. **Mất một UNIQUE index.** `mdl_enrol_lti_lti2_share_key` có 2 unique index; pgloader
   đặt tên `idx_<oid>_<tên-gốc>` dài giống nhau ở đầu, PostgreSQL cắt còn 63 ký tự thành
   **trùng tên** → lỗi `42P07 relation already exists`, chỉ tạo được 1. Mất ràng buộc
   unique trên cột `sharekey`.
   → `fix` đối chiếu index hai phía theo `(bảng, cột, unique)` — không theo tên vì
   pgloader đổi tên — rồi tạo bù với tên rút gọn kèm hậu tố băm.

## Ba lỗi môi trường đã phải sửa để chạy được

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

## Kiểm chứng

```bash
make verify              # doi chieu 2 phia: so dong, kieu cot, index, sequence
./check_moodle_schema.sh # chay check_database_schema.php cua chinh Moodle
```

`make verify` so **từng cột** giữa MSSQL và PostgreSQL (tên, kiểu, độ dài, NOT NULL).
Kết quả hiện tại: **6532/6547 cột khớp tuyệt đối**. 15 cột khác biệt đều nằm ở bảng
tuỳ biến và đều là chuẩn hoá có lợi, không phải mất mát:

- 5 cột tên chữ hoa (`Contextid`, `createdAt`, `updatedAt`) bị hạ về chữ thường.
  PostgreSQL luôn hạ identifier không đóng ngoặc kép, và Moodle luôn dùng chữ thường.
  Lưu ý: nếu plugin tuỳ biến của bạn có SQL thô viết `"createdAt"` trong ngoặc kép thì
  phải sửa thành `createdat`.
- 10 cột `id` kiểu `integer` thành `bigint` (pgloader mở rộng cột identity). Moodle vốn
  định nghĩa `id` là bigint nên đây là hướng đúng.

### Chạy thử site thật

```bash
./run_moodle_test.sh          # dung site test tai http://localhost:8899
./run_moodle_test.sh stop     # dung va don dep
```

Dựng một container Moodle riêng, port riêng, dùng **bản copy** của `moodledata` — không
đụng gì đến site đang chạy. Kết quả lần chạy gần nhất với source
`/home/vulethanh/moodle-docker/src/ptsc/source` (Moodle 4.4+):

- `/`, `/login/index.php`, `/admin/index.php`, `/course/index.php` đều **HTTP 200**.
  Trang admin hiện đúng server checks: PostgreSQL 18.6 (yêu cầu ≥ 13), PHP 8.3.31
  (yêu cầu ≥ 8.1).
- 17 request, **không có PHP error nào** trong log Apache.
- Đọc metadata và chạy điều kiện so sánh bằng trên **cả 729 bảng** qua lớp DML của
  Moodle: 1143 cột `meta_type C` (char), 635 cột `X` (clob), **0 lỗi**.

#### Site báo "An upgrade is pending" — không phải do migration

`moodle_needs_upgrading()` so hash version của **toàn bộ plugin trên đĩa** với giá trị
`allversionshash` lưu trong database:

| | |
|---|---|
| `allversionshash` trong MSSQL nguồn | `eee2da0ee2c851a25fda5577fd93600d0516e7d6` |
| `allversionshash` trong PostgreSQL | `eee2da0ee2c851a25fda5577fd93600d0516e7d6` — **giống hệt** |
| hash tính từ source code | `989ac6a66b18d9bd7b95b448cacb5fb75f19dd2b` — **khác** |

Nguyên nhân: source tree thiếu **14 plugin** mà database có cài — `mod_game`,
`block_xp`, `block_quickmail`, `block_notifications`, `block_mycoursestatus`,
`qtype_recordrtc`, `auth_oidc`, `factor_loginbanner`, `factor_secq`,
`gradingform_checklist`, `theme_adaptable`, `local_chatbot`, `local_ctm`, `vnr_chatbot`.
Chiều ngược lại là 0: không có plugin nào thừa code.

Nói cách khác, `src/ptsc/source` **không phải codebase đang chạy LMS_PTSC**. Muốn site
lên bình thường thì bổ sung 14 plugin đó vào source, hoặc dùng đúng codebase gốc.

> `mdl_config.version` trong database là `2024042201.1` còn `version.php` là
> `2024042201.10`. Đã đối chiếu: **MSSQL nguồn cũng là `2024042201.1`** (len=12) — bản
> sao trung thực, không mất ký tự.

### Về các sai lệch mà `check_database_schema.php` còn báo

Còn khoảng 1408 dòng, **không phải do migration**:

| Loại | Số lượng | Vì sao |
|---|---:|---|
| `Missing index` | 1092 | **Nguồn MSSQL vốn đã thiếu.** Nguồn chỉ có 140 index ngoài primary key, Moodle 4.4 mong đợi hơn 1200. Ví dụ `mdl_course` bên MSSQL chỉ có mỗi primary key. Bản sao có đúng 140 = bằng nguồn. |
| `has default` / `NOT NULL` | 158 | Cột tuỳ biến của nguồn lệch so với XMLDB. Đối chiếu NOT NULL hai phía khớp 100%. |
| `table/column is not expected` | 61 | Bảng và cột tuỳ biến do đội phát triển thêm vào. |
| `incorrect type`, `length`, `size` | ~97 | Kiểu ở nguồn lệch chuẩn Moodle, ví dụ `fraction` là `decimal(12,7)` trong khi Moodle mong `(10,7)`. |

Muốn tạo bù các index thiếu (làm database đích **tốt hơn** nguồn — đúng chuẩn XMLDB,
truy vấn nhanh hơn nhiều):

```bash
./fix_moodle_indexes.sh --dry-run   # xem truoc 1093 lenh CREATE INDEX
./fix_moodle_indexes.sh             # chay that
```

Đây là **tuỳ chọn**, không chạy tự động, vì nó thay đổi database vượt ra ngoài phạm vi
một bản sao trung thực. Các lệnh do chính `check_database_schema.php` sinh ra.

> Không chạy được `check_database_schema.php` trên MSSQL nguồn để so sánh: driver
> `sqlsrv` của Moodle không hỗ trợ kiểu `numeric` (chỉ `decimal`) và ném
> `error/invalidsqlsrvnativetype`. Nguồn có 3 cột `numeric` — thêm một dấu hiệu nữa cho
> thấy database MSSQL này không do Moodle tạo ra.

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

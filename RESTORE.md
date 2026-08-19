# Restore LMS_PTSC lên server PostgreSQL của bạn

## 1. Chọn đúng file

`make dump` sinh ra hai bản trong `backup/`, nội dung dữ liệu **giống hệt nhau**,
chỉ khác vài dòng lệnh ở đầu file:

| Phiên bản server đích | Dùng file |
|---|---|
| PostgreSQL 18 trở lên | `lms_ptsc.sql` (hoặc `.sql.gz`) |
| PostgreSQL 13 → 17 | `lms_ptsc-pg13-17.sql` (hoặc `.sql.gz`) |

Bản `pg13-17` bỏ đi 2 thứ mà server cũ không hiểu:

- `\restrict` / `\unrestrict` — lệnh của `psql` mới, `psql` cũ báo *invalid command*.
- `SET transaction_timeout = 0;` — tham số chỉ có từ PostgreSQL 17, server cũ báo
  *unrecognized configuration parameter*.

> Không chắc server chạy bản nào? Chạy `psql -V` trên server đó, hoặc cứ dùng bản
> `pg13-17` — nó restore được trên **mọi** phiên bản từ 13 trở lên.

Kích thước: mỗi bản 175 MB, nén `.gz` còn 15 MB. Chuyển file thì dùng bản `.gz`.

## 2. Chuyển file sang server

```bash
scp backup/lms_ptsc-pg13-17.sql.gz user@server:/tmp/
```

## 3. Tạo database rỗng

File dump **không** chứa lệnh `CREATE DATABASE`, nên bạn tự tạo và tự chọn tên.
Bắt buộc dùng encoding UTF8 — nếu không tiếng Việt sẽ hỏng.

```sql
CREATE DATABASE lms_ptsc
  WITH ENCODING 'UTF8' LC_COLLATE 'en_US.utf8' LC_CTYPE 'en_US.utf8' TEMPLATE template0;
```

Nếu server chưa có locale `en_US.utf8` thì thay bằng `'C'` — Moodle vẫn chạy, chỉ
khác thứ tự sắp xếp chuỗi.

## 4. Restore

```bash
gunzip -c /tmp/lms_ptsc-pg13-17.sql.gz \
  | psql -h localhost -U <user> -d lms_ptsc -v ON_ERROR_STOP=1
```

Với file chưa nén:

```bash
psql -h localhost -U <user> -d lms_ptsc -v ON_ERROR_STOP=1 -f lms_ptsc-pg13-17.sql
```

`ON_ERROR_STOP=1` rất quan trọng: không có nó, `psql` gặp lỗi vẫn chạy tiếp và bạn
sẽ nhận một database thiếu dữ liệu mà tưởng là thành công.

Dump dùng `--no-owner --no-privileges`, nên mọi object sẽ thuộc về user nào chạy
lệnh restore — không cần tạo trước role `moodle` trên server đích.

## 5. Kiểm tra sau khi restore

```sql
-- Phai ra 729
SELECT count(*) FROM information_schema.tables
WHERE table_schema='public' AND table_type='BASE TABLE';

-- Phai ra 808053 (hoac lon hon neu ban dump lai sau nay)
SELECT sum(cnt) FROM (
  SELECT (xpath('/row/c/text()', query_to_xml(
    'SELECT count(*) AS c FROM public.'||quote_ident(table_name), false, true, '')))[1]::text::bigint AS cnt
  FROM information_schema.tables
  WHERE table_schema='public' AND table_type='BASE TABLE') t;

-- Tieng Viet phai hien dung dau
SELECT id, fullname FROM mdl_course WHERE id = 11150;

-- Phai ra 0 — Moodle dung index chu khong dung foreign key
SELECT count(*) FROM information_schema.table_constraints
WHERE table_schema='public' AND constraint_type='FOREIGN KEY';

-- Phai ra 0 — Moodle yeu cau smallint chu khong phai boolean
SELECT count(*) FROM information_schema.columns
WHERE table_schema='public' AND data_type='boolean';

-- Phai ra 1143 varchar(n) va 0 cot varchar khong gioi han do dai.
-- Neu ra 0 varchar(n) la dump cu (truoc ban va typemod) -> Moodle se chet voi
-- loi "textconditionsnotallowed" ngay khi khoi dong.
SELECT count(*) FROM information_schema.columns
WHERE table_schema='public' AND data_type='character varying';

-- Phai ra 121 — cot numeric deu co precision. Neu ra 0 thi cot diem so bi mat
-- precision, Moodle bao 'size is (-1,65531), expected (10,5)'.
SELECT count(*) FROM information_schema.columns
WHERE table_schema='public' AND data_type='numeric' AND numeric_precision IS NOT NULL;
```

Kiem tra bang chinh Moodle (chac chan nhat):

```bash
php admin/cli/check_database_schema.php
```

Ky vong: **khong con dong nao chua "size is (-1,65531)"**. Cac dong "Missing index"
va sai lech ve default/NOT NULL tren bang tuy bien la dac diem san co cua database
nguon, khong phai loi restore — xem muc "Kiem chung" trong README.md.

Kiểm tra sequence — đây là thứ hay hỏng nhất sau khi restore. `last_value` phải
**lớn hơn** `max(id)`, nếu không Moodle sẽ báo trùng khoá khi tạo bản ghi mới:

```sql
SELECT (SELECT max(id) FROM mdl_course) AS max_id, last_value FROM mdl_course_id_seq;
```

Nếu sequence sai (do restore thiếu phần `setval`), chạy lệnh này để sửa toàn bộ:

```sql
DO $$
DECLARE r record; seqname text;
BEGIN
  FOR r IN SELECT table_name FROM information_schema.columns
           WHERE table_schema='public' AND column_name='id'
  LOOP
    seqname := pg_get_serial_sequence('public.'||quote_ident(r.table_name), 'id');
    IF seqname IS NOT NULL THEN
      EXECUTE format('SELECT setval(%L, COALESCE((SELECT max(id) FROM public.%I),0)+1, false)',
                     seqname, r.table_name);
    END IF;
  END LOOP;
END $$;
```

Cuối cùng chạy `VACUUM ANALYZE;` để planner có thống kê.

## 6. Trỏ Moodle sang database mới

```php
$CFG->dbtype   = 'pgsql';
$CFG->dblibrary= 'native';
$CFG->dbhost   = 'your-server';
$CFG->dbname   = 'lms_ptsc';
$CFG->dbuser   = 'your-user';
$CFG->dbpass   = 'your-password';
$CFG->prefix   = 'mdl_';
$CFG->dboptions = array('dbport' => 5432);
```

Rồi:

1. **Copy `moodledata`** sang server mới. Database **không** chứa file thật (ảnh,
   tài liệu upload) — Moodle lưu ở `moodledata/filedir`. Bỏ bước này là ảnh và
   file hỏng hết dù database đúng hoàn toàn. Đây là lỗi phổ biến nhất khi migrate.
2. `php admin/cli/purge_caches.php`
3. `php admin/cli/check_database_schema.php` — kỳ vọng "No differences found".

## Lưu ý: dump là bản chụp tại một thời điểm

Database nguồn SQL Server vẫn đang chạy và ghi thêm dữ liệu. File dump chỉ đúng
tại thời điểm chạy `make dump`. Khi cutover thật, làm lại tuần tự:

```bash
make reset      # xoa database dich
make migrate    # chuyen lai tu SQL Server
make dump       # xuat file .sql moi
```

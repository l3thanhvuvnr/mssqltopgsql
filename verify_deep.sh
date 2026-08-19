#!/bin/bash
# Kiem chung doc lap sau migration.
#
# Vi sao can file nay: buoc verify cua tool lay so dong NGUON tu sys.partitions
# (so uoc luong, chup luc bat dau chay) roi so voi COUNT(*) chinh xac o DICH.
# Database nguon dang chay that, nen cac bang ghi lien tuc (mdl_task_log,
# mdl_logstore_standard_log...) luon bi bao "mismatch" du ban sao hoan toan dung.
# Script nay dem chinh xac CA HAI phia cho dung cac bang bi bao lech.
#
# Doc thong tin ket noi tu config.yml (file nay khong duoc commit).
set -u
cd "$(dirname "$0")"
CFG="${1:-config.yml}"
[ -f "$CFG" ] || { echo "Khong tim thay $CFG — copy tu config.example.yml roi dien thong tin."; exit 1; }

eval "$(python3 - "$CFG" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))
s, t = c['source_mssql'], c['target_pgsql']
for k, v in [('SRC_HOST',s['host']),('SRC_PORT',s['port']),('SRC_DB',s['db']),
             ('SRC_USER',s['user']),('SRC_PW',s['password']),
             ('DST_DB',t['db']),('DST_USER',t['user'])]:
    print(f"{k}={v!r}".replace("'", '"', 2) if False else f"{k}='{v}'")
PY
)"
PGC="${PG_CONTAINER:-ptsc-pg18}"

ms() { docker run --rm mcr.microsoft.com/mssql-tools:latest /opt/mssql-tools/bin/sqlcmd \
         -S "$SRC_HOST,$SRC_PORT" -U "$SRC_USER" -P "$SRC_PW" -d "$SRC_DB" \
         -l 60 -h -1 -W -Q "SET NOCOUNT ON; $1" 2>/dev/null | tr -d ' \r' | head -1; }
# Chi cat khoang trang hai dau, KHONG xoa khoang trang ben trong (vd "304 MB").
pg() { docker exec "$PGC" psql -U "$DST_USER" -d "$DST_DB" -tAc "$1" 2>&1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }

echo "=== 1. So bang ==="
echo "MSSQL=$(ms "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME LIKE 'mdl!_%' ESCAPE '!';")  PG=$(pg "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")"

echo "=== 2. Dem chinh xac cac bang report bao lech ==="
awk -F'|' 'NR>6 && NF>=5 {gsub(/^ +| +$/,"",$5); gsub(/^ +| +$/,"",$2); if($5=="mismatch"||$5=="missing") print $2}' output/report.md 2>/dev/null > /tmp/mism.txt
n=$(wc -l < /tmp/mism.txt)
echo "so bang bao lech: $n"
while read -r t; do
  [ -z "$t" ] && continue
  s=$(ms "SELECT COUNT(*) FROM $t;"); d=$(pg "SELECT count(*) FROM \"$t\";")
  if [ "$s" = "$d" ]; then v="OK (report lech do sys.partitions uoc luong)"
  else
    # nguon ghi them sau khi copy? -> dich phai la tien to theo id
    mx=$(pg "SELECT COALESCE(max(id),0) FROM \"$t\";")
    le=$(ms "SELECT COUNT(*) FROM $t WHERE id <= $mx;")
    [ "$le" = "$d" ] && v="OK (nguon ghi them $((s-d)) dong SAU khi copy)" || v=">>> LECH THAT"
  fi
  printf '  %-42s MSSQL=%-9s PG=%-9s %s\n' "$t" "$s" "$d" "$v"
done < /tmp/mism.txt

echo "=== 3. Toan ven tieng Viet ==="
echo "ky tu thay the U+FFFD: $(pg "SELECT count(*) FROM mdl_course WHERE fullname LIKE '%'||chr(65533)||'%';")"
echo "user co dau tieng Viet: $(pg "SELECT count(*) FROM mdl_user WHERE lastname ~ '[À-ỹ]';")"

echo "=== 4. Cau truc (so sanh 2 phia) ==="
echo "index thuong  MSSQL=$(ms "SELECT COUNT(*) FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id WHERE i.index_id>0 AND i.is_primary_key=0;")  PG=$(pg "SELECT count(*) FROM pg_indexes i WHERE i.schemaname='public' AND NOT EXISTS (SELECT 1 FROM information_schema.table_constraints c WHERE c.table_schema='public' AND c.constraint_type='PRIMARY KEY' AND c.constraint_name=i.indexname);")"
echo "primary key   MSSQL=$(ms "SELECT COUNT(*) FROM sys.indexes i JOIN sys.tables t ON t.object_id=i.object_id WHERE i.is_primary_key=1;")  PG=$(pg "SELECT count(*) FROM information_schema.table_constraints WHERE table_schema='public' AND constraint_type='PRIMARY KEY';")"
echo "foreign key (phai =0 cho Moodle):  $(pg "SELECT count(*) FROM information_schema.table_constraints WHERE table_schema='public' AND constraint_type='FOREIGN KEY';")"
echo "cot boolean (phai =0 cho Moodle):  $(pg "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND data_type='boolean';")"

echo "=== 5. Sequence (max_id phai < last_value) ==="
for tb in mdl_user mdl_course mdl_files mdl_context; do
  echo "  $(pg "SELECT '$tb: max_id='||COALESCE((SELECT max(id) FROM $tb),0)||' seq_last='||(SELECT last_value FROM ${tb}_id_seq);")"
done

echo "=== 6. Doi chieu KIEU DU LIEU tung cot giua 2 phia ==="
# Chieu kieu MSSQL sang kieu PostgreSQL mong doi, roi so voi thuc te ben dich.
# Day la bang chung truc tiep ve do trung thuc cua migration.
# Truyen SQL qua FILE (-i) thay vi -Q: chuoi nhieu dong qua -Q khong on dinh.
cat > /tmp/.cols_src.sql <<'SQL'
SET NOCOUNT ON;
SELECT TABLE_NAME+'|'+COLUMN_NAME+'|'+
  CASE
    WHEN DATA_TYPE IN ('bigint') THEN 'bigint'
    WHEN DATA_TYPE IN ('int') THEN 'integer'
    WHEN DATA_TYPE IN ('smallint','tinyint','bit') THEN 'smallint'
    WHEN DATA_TYPE IN ('decimal','numeric') THEN 'numeric('+CAST(NUMERIC_PRECISION AS VARCHAR)+','+CAST(ISNULL(NUMERIC_SCALE,0) AS VARCHAR)+')'
    WHEN DATA_TYPE IN ('float') THEN 'double precision'
    WHEN DATA_TYPE IN ('real') THEN 'real'
    WHEN DATA_TYPE IN ('nvarchar','varchar','nchar','char') AND CHARACTER_MAXIMUM_LENGTH > 0
         THEN 'character varying('+CAST(CHARACTER_MAXIMUM_LENGTH AS VARCHAR)+')'
    WHEN DATA_TYPE IN ('nvarchar','varchar','text','ntext','uniqueidentifier','xml') THEN 'text'
    WHEN DATA_TYPE IN ('varbinary','image','binary') THEN 'bytea'
    WHEN DATA_TYPE IN ('datetime','datetime2','smalldatetime') THEN 'timestamp without time zone'
    ELSE '?'+DATA_TYPE
  END
+'|'+IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME LIKE 'mdl!_%' ESCAPE '!'
ORDER BY TABLE_NAME, COLUMN_NAME;
SQL

docker run --rm -v /tmp/.cols_src.sql:/q.sql mcr.microsoft.com/mssql-tools:latest \
  /opt/mssql-tools/bin/sqlcmd -S "$SRC_HOST,$SRC_PORT" -U "$SRC_USER" -P "$SRC_PW" \
  -d "$SRC_DB" -l 60 -h -1 -W -i /q.sql 2>/dev/null \
  | tr -d ' \r' | grep '|' | sort > /tmp/.cols_src

pg "SELECT table_name||'|'||column_name||'|'||
      CASE WHEN data_type='character varying' THEN 'character varying('||character_maximum_length||')'
           WHEN data_type='numeric' AND numeric_precision IS NOT NULL
                THEN 'numeric('||numeric_precision||','||numeric_scale||')'
           ELSE data_type END
      ||'|'||is_nullable
    FROM information_schema.columns WHERE table_schema='public'
    ORDER BY table_name, column_name;" | tr -d ' ' | grep '|' | sort > /tmp/.cols_dst

echo "cot ben MSSQL : $(wc -l < /tmp/.cols_src)"
echo "cot ben PG    : $(wc -l < /tmp/.cols_dst)"
if diff -q /tmp/.cols_src /tmp/.cols_dst >/dev/null; then
  echo "KHOP HOAN TOAN — moi cot dung kieu, do dai va NOT NULL."
else
  echo "Cac cot lech (nguon < / dich >):"
  diff /tmp/.cols_src /tmp/.cols_dst | grep -E '^[<>]' | head -25
  echo "  tong so dong lech: $(diff /tmp/.cols_src /tmp/.cols_dst | grep -cE '^[<>]')"
fi

echo "=== 7. Kich thuoc DB dich ==="
echo "$(pg "SELECT pg_size_pretty(pg_database_size('$DST_DB'));")"

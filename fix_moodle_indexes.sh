#!/bin/bash
# Tao cac index ma Moodle mong doi nhung database KHONG co.
#
# TUY CHON — khong chay tu dong. Database nguon MSSQL von da thieu cac index nay
# (nguon chi co 140 index ngoai primary key, Moodle 4.4 mong doi hon 1200), nen
# ban sao thieu chung la trung thuc voi nguon, khong phai loi migration.
# Chay script nay lam database DICH tot hon nguon: dung chuan XMLDB cua Moodle,
# truy van nhanh hon nhieu.
#
# Cac lenh CREATE INDEX do chinh check_database_schema.php cua Moodle sinh ra.
# Moi lenh chay rieng: mot lenh loi khong chan cac lenh con lai. Index UNIQUE co
# the loi neu du lieu dang co ban ghi trung — do la van de du lieu cua nguon va
# script se bao ro de ban xu ly.
#
#   ./fix_moodle_indexes.sh --dry-run   # chi in ra, khong chay
#   ./fix_moodle_indexes.sh             # chay that
set -u
cd "$(dirname "$0")"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
CFG="${CFG:-config.yml}"
PGC="${PG_CONTAINER:-ptsc-pg18}"

eval "$(python3 - "$CFG" <<'PY'
import sys, yaml
t = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))['target_pgsql']
print(f"DB='{t['db']}'"); print(f"USER='{t['user']}'")
PY
)"

echo "Lay danh sach index thieu tu check_database_schema.php ..."
./check_moodle_schema.sh > /tmp/.mdlschema.txt 2>&1
grep -E '^CREATE (UNIQUE )?INDEX ' /tmp/.mdlschema.txt > /tmp/.mdlidx.sql
total=$(wc -l < /tmp/.mdlidx.sql)
echo "Moodle de xuat $total lenh CREATE INDEX."

if [ "$total" -eq 0 ]; then echo "Khong co gi de tao."; exit 0; fi
if [ "$DRY" -eq 1 ]; then echo ""; head -20 /tmp/.mdlidx.sql; echo "... (xem het: /tmp/.mdlidx.sql)"; exit 0; fi

ok=0; fail=0; : > /tmp/.mdlidx_fail.txt
while IFS= read -r stmt; do
  if docker exec "$PGC" psql -U "$USER" -d "$DB" -q -v ON_ERROR_STOP=1 -c "$stmt" >/dev/null 2>/tmp/.e; then
    ok=$((ok+1))
  else
    fail=$((fail+1)); { echo "$stmt"; sed 's/^/    /' /tmp/.e; } >> /tmp/.mdlidx_fail.txt
  fi
  printf "\r  da tao %d/%d (loi %d)" "$ok" "$total" "$fail"
done < /tmp/.mdlidx.sql
echo ""

echo ""
echo "Tao thanh cong : $ok"
echo "That bai       : $fail"
[ "$fail" -gt 0 ] && { echo ""; echo "Chi tiet loi (thuong do du lieu trung khi tao UNIQUE index):"; head -30 /tmp/.mdlidx_fail.txt; }
docker exec "$PGC" psql -U "$USER" -d "$DB" -q -c "ANALYZE;" >/dev/null 2>&1
echo ""
echo "Da chay ANALYZE. Kiem tra lai bang: ./check_moodle_schema.sh"

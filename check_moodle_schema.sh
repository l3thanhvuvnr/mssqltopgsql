#!/bin/bash
# Chay admin/cli/check_database_schema.php cua Moodle len database dich.
# Day la kiem chung CO THAM QUYEN: Moodle tu doi chieu schema that voi dinh nghia
# XMLDB cua no. Ky vong "No differences found".
#
#   ./check_moodle_schema.sh [duong-dan-source-moodle]
set -u
cd "$(dirname "$0")"
SRC="${1:-/home/vulethanh/moodle-docker/src/ptsc/source}"
CFG="${CFG:-config.yml}"
NET="${NET:-ptsc-pg18_default}"
IMG="${IMG:-moodlehq/moodle-php-apache:8.3}"

[ -d "$SRC" ] || { echo "Khong tim thay source Moodle: $SRC"; exit 1; }
[ -f "$SRC/admin/cli/check_database_schema.php" ] || { echo "$SRC khong phai source Moodle."; exit 1; }
[ -f "$CFG" ] || { echo "Thieu $CFG."; exit 1; }

eval "$(python3 - "$CFG" <<'PY'
import sys, yaml
t = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))['target_pgsql']
for k, v in [('DB', t['db']), ('USER', t['user']), ('PW', t['password'])]:
    print(f"{k}='{v}'")
PY
)"
# Cho phep tro sang database khac (vd ban vua restore tu file dump de kiem tra).
DB="${MDLTEST_DB:-$DB}"

# config.php cua moodle-docker doc tu env va hardcode dbhost='db' — trung dung
# ten service PostgreSQL trong docker-compose.yml nen chay thang tren network do.
DATAROOT=$(mktemp -d)
trap 'rm -rf "$DATAROOT"' EXIT
chmod 777 "$DATAROOT"

echo "Source Moodle : $SRC"
echo "Database      : $DB (user $USER) qua network $NET"
echo ""
docker run --rm --network "$NET" \
  -v "$SRC":/var/www/html:ro \
  -v "$DATAROOT":/var/www/moodledata \
  -e MOODLE_DOCKER_DBTYPE=pgsql \
  -e MOODLE_DOCKER_DBNAME="$DB" \
  -e MOODLE_DOCKER_DBUSER="$USER" \
  -e MOODLE_DOCKER_DBPASS="$PW" \
  -w /var/www/html \
  "$IMG" php admin/cli/check_database_schema.php

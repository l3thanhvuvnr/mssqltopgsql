#!/bin/bash
# Dung mot Moodle THAT tro vao database da migrate, de kiem tra site co chay khong.
#
# Chay tren container rieng, port rieng, va mot BAN COPY cua moodledata — khong
# dung gi den site dang chay.
#
#   ./run_moodle_test.sh          # dung site test
#   ./run_moodle_test.sh stop     # dung va don dep
set -u
cd "$(dirname "$0")"
CFG="${CFG:-config.yml}"
SRC="${MDLTEST_SRC:-/home/vulethanh/moodle-docker/src/ptsc/source}"
DATA_SRC="${MDLTEST_DATA:-/home/vulethanh/moodle-docker/src/ptsc/moodledata}"
CONTAINER="${MDLTEST_CONTAINER:-ptsc-pg18-web}"
PORT="${MDLTEST_PORT:-8899}"
NET="${MDLTEST_NET:-ptsc-pg18_default}"
IMG="${MDLTEST_IMG:-moodlehq/moodle-php-apache:8.3}"
WORK=".smoketest"

if [ "${1:-}" = "stop" ]; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "Da xoa container $CONTAINER."
  rm -rf "$WORK" && echo "Da xoa $WORK."
  exit 0
fi

[ -d "$SRC" ] || { echo "Khong tim thay source Moodle: $SRC"; exit 1; }
[ -f "$CFG" ] || { echo "Thieu $CFG."; exit 1; }

eval "$(python3 - "$CFG" <<'PY'
import sys, yaml
t = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))['target_pgsql']
for k, v in [('DB', t['db']), ('USER', t['user']), ('PW', t['password'])]:
    print(f"{k}='{v}'")
PY
)"

if [ ! -d "$WORK/moodledata" ]; then
  echo "Copy moodledata (mot lan, ~600MB)..."
  mkdir -p "$WORK"
  cp -a "$DATA_SRC" "$WORK/moodledata" 2>/dev/null || true
  # Xoa cache/session cu de Moodle sinh lai theo database moi.
  rm -rf "$WORK"/moodledata/cache/* "$WORK"/moodledata/localcache/* \
         "$WORK"/moodledata/sessions/* 2>/dev/null || true
  chmod -R 777 "$WORK/moodledata" 2>/dev/null || true
fi

docker rm -f "$CONTAINER" >/dev/null 2>&1
docker run -d --name "$CONTAINER" --network "$NET" \
  -v "$SRC":/var/www/html:ro \
  -v "$PWD/$WORK/moodledata":/var/www/moodledata \
  -e MOODLE_DOCKER_DBTYPE=pgsql -e MOODLE_DOCKER_DBNAME="$DB" \
  -e MOODLE_DOCKER_DBUSER="$USER" -e MOODLE_DOCKER_DBPASS="$PW" \
  -e MOODLE_DOCKER_WEB_HOST=localhost -e MOODLE_DOCKER_WEB_PORT="$PORT" \
  -e MOODLE_DOCKER_RUNNING=1 \
  -p "$PORT":80 "$IMG" >/dev/null || exit 1

echo -n "Cho Moodle san sang"
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -L "http://localhost:$PORT/" 2>/dev/null || echo 000)
  [ "$code" = "200" ] && { echo " — san sang."; break; }
  printf "."; sleep 2
done
echo ""
for p in / /login/index.php /admin/index.php /course/index.php; do
  printf "  %-24s HTTP %s\n" "$p" \
    "$(curl -s -o /dev/null -w '%{http_code}' -L "http://localhost:$PORT$p")"
done
echo ""
echo "  Site test: http://localhost:$PORT"
echo "  Log PHP  : docker logs $CONTAINER"
echo "  Don dep  : ./run_moodle_test.sh stop"

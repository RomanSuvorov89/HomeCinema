#!/usr/bin/env bash
# Update the existing standalone recommender; optionally verify one known series first.
set -euo pipefail
TARGET="${1:?Pass the existing kinopoisk-sync directory}"
REF="${2:?Pass a HomeCinema commit SHA}"
CHECK_ID="${3:-}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'Expected a full commit SHA'; exit 1; }
[[ -z "$CHECK_ID" || "$CHECK_ID" =~ ^[0-9]+$ ]] || { echo 'Invalid check ID'; exit 1; }
cd "$TARGET"
[[ -f Dockerfile && -f episode_schedule.py ]] || { echo 'Wrong recommender directory'; exit 1; }
CONTAINER="${RECOMMENDER_CONTAINER:-kinopoisk-sync}"
SERVICE="${RECOMMENDER_SERVICE:-kinopoisk-sync}"
WORK="$(mktemp -d)"
CHECK_FILE="/tmp/homecinema-kinoafisha-$(basename "$WORK").py"
cleanup() {
  docker exec "$CONTAINER" rm -f "$CHECK_FILE" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
BASE="https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF/server/recommender"
for file in episode_schedule.py kinoafisha.py; do
  curl -fsSL --connect-timeout 5 --max-time 30 "$BASE/$file" -o "$WORK/$file"
done
python3 - "$WORK" <<'PY'
import ast,sys
from pathlib import Path
for p in Path(sys.argv[1]).glob('*.py'):ast.parse(p.read_text())
print('Синтаксис проверен')
PY
if [[ -n "$CHECK_ID" ]]; then
  docker cp "$WORK/kinoafisha.py" "$CONTAINER:$CHECK_FILE" >/dev/null
  docker exec -i "$CONTAINER" python -u - "$CHECK_FILE" "$CHECK_ID" <<'PY'
import importlib.util,sqlite3,sys
spec=importlib.util.spec_from_file_location('kinoafisha_check',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
c=sqlite3.connect('file:/data/recommender.sqlite3?mode=ro',uri=True);c.row_factory=sqlite3.Row
media=c.execute('SELECT * FROM media WHERE kp_id=?',(int(sys.argv[2]),)).fetchone()
if not media:raise SystemExit('Сериал не найден в существующей базе')
print('Проверяем поиск и расписание Киноафиши:',media['title'],flush=True)
episodes,url=module.load(media)
print('Совпадение:',url)
print('Получено серий:',len(episodes),'последняя:',episodes[-1])
PY
fi
STAMP="$(date +%Y%m%d-%H%M%S)"
for file in episode_schedule.py kinoafisha.py Dockerfile; do
  if [[ -f "$file" ]]; then cp -a "$file" "$file.before-kinoafisha-$STAMP"; fi
done
# Validate the insertion anchor before replacing any application source.
python3 - <<'PY'
from pathlib import Path
p=Path('Dockerfile');s=p.read_text();line='COPY kinoafisha.py /app/kinoafisha.py'
if line not in s:
    anchor='COPY episode_schedule.py /app/episode_schedule.py'
    if s.count(anchor)!=1:raise SystemExit('Неожиданный Dockerfile: исходники не изменены')
    p.write_text(s.replace(anchor,anchor+'\n'+line))
PY
cp "$WORK/episode_schedule.py" episode_schedule.py
cp "$WORK/kinoafisha.py" kinoafisha.py
docker compose up -d --build "$SERVICE"
echo "Обновлено. Резервные копии: *.before-kinoafisha-$STAMP"
echo "Логи: docker logs --since 5m --tail 100 $CONTAINER"

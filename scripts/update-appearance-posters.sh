#!/usr/bin/env bash
# Existing installation: preserve all local URLs, configuration, data and bind mounts.
set -euo pipefail
REF="${1:?Pass full HomeCinema commit SHA}"
RECOMMENDER="${2:-/home/romans/kinopoisk-sync}"
POSTERS="${3:-/home/romans/poster-cache}"
LAMPAINIT="${4:-/home/romans/lampac/plugins/lampainit.js}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
BASE="https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF"
fetch() { curl -fsSL --connect-timeout 5 --max-time 30 "$BASE/$1" -o "$WORK/$2"; }
fetch scripts/apply-home-actions.py apply-actions.py
fetch scripts/set-apple-theme.py set-apple-theme.py
for name in server.py kinoafisha_posters.py posters.js Dockerfile; do
  fetch "server/poster-cache/$name" "$name"
done
python3 - "$WORK" <<'PY'
import ast
from pathlib import Path
import sys
for file in Path(sys.argv[1]).glob('*.py'):
    ast.parse(file.read_text())
print('Синтаксис обновления проверен')
PY
test -f "$POSTERS/.env"
test -f "$POSTERS/install.py"
test -w "$LAMPAINIT"
STAMP="$(date +%Y%m%d-%H%M%S)"
for name in server.py kinoafisha_posters.py posters.js Dockerfile; do
  if [[ -f "$POSTERS/$name" ]]; then cp -a "$POSTERS/$name" "$POSTERS/$name.before-appearance-$STAMP"; fi
  cp "$WORK/$name" "$POSTERS/$name"
done
(cd "$POSTERS" && docker compose up -d --build poster-cache)
python3 "$WORK/apply-actions.py" "$RECOMMENDER" "$LAMPAINIT" "$REF"
(cd "$RECOMMENDER" && docker compose up -d --build kinopoisk-sync)
(cd "$POSTERS" && python3 install.py)
python3 "$WORK/set-apple-theme.py" --path "$LAMPAINIT" --ref "$REF"
# Keep the offline removal command available after the temporary work directory is removed.
cp "$WORK/set-apple-theme.py" "$(dirname "$LAMPAINIT")/set-apple-theme.py"
docker restart lampac
echo 'Готово. Полностью закройте Lampa на ТВ и откройте снова; на ПК Ctrl+F5.'
echo 'Источники постеров: docker logs --since 5m roman-poster-cache'
echo "Копии исходников: *.before-appearance-$STAMP; копии lampainit.js напечатаны выше."

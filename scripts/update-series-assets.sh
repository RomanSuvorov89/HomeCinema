#!/usr/bin/env bash
# Update only the existing poster service and its embedded client.
set -euo pipefail
REF="${1:?Pass full HomeCinema commit SHA}"
POSTERS="${2:-/home/romans/poster-cache}"
CATALOG="${3:-/home/romans/kinopoisk-sync}"
LAMPAINIT="${4:-/home/romans/lampac/plugins/lampainit.js}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
for name in server.py posters.js; do
  curl -fsSL --connect-timeout 5 --max-time 30 \
    "https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF/server/poster-cache/$name" -o "$WORK/$name"
done
python3 - "$WORK/server.py" <<'PY'
import ast,sys
from pathlib import Path
ast.parse(Path(sys.argv[1]).read_text())
print('Синтаксис проверен')
PY
test -f "$POSTERS/.env"
test -f "$POSTERS/install.py"
test -f "$POSTERS/kinoafisha_posters.py"
test -w "$LAMPAINIT"
STAMP="$(date +%Y%m%d-%H%M%S)"
for name in server.py posters.js; do
  cp -a "$POSTERS/$name" "$POSTERS/$name.before-series-assets-$STAMP"
  cp "$WORK/$name" "$POSTERS/$name"
done
cd "$POSTERS"
docker compose build poster-cache
docker compose up -d poster-cache
# Public cached dates endpoint is checked inside the service; no router changes.
docker compose exec -T poster-cache python -c '
import json,time
from urllib.request import urlopen
for attempt in range(20):
    try:
        with urlopen("http://127.0.0.1:9121/series/kp/1.json",timeout=3) as response:
            assert isinstance(json.load(response)["episodes"],list)
        print("Кэш изображений и дат готов")
        break
    except Exception:
        if attempt==19: raise
        time.sleep(1)
'
python3 install.py
# Restore the existing profile-first order without changing catalog server sources.
if [[ -f "$CATALOG/profiles-client.js" && -f "$CATALOG/install.py" ]]; then
  (cd "$CATALOG" && python3 install.py "$LAMPAINIT")
fi
docker restart "${LAMPAC_CONTAINER:-lampac}"
echo 'Готово. На ПК Ctrl+F5, на ТВ полностью закройте и откройте Lampa.'
echo "Копии исходников: $POSTERS/*.before-series-assets-$STAMP"

#!/usr/bin/env bash
set -euo pipefail
REF="${1:?Pass full HomeCinema commit SHA}"
TARGET="${2:-/home/romans/kinopoisk-sync}"
LAMPAINIT="${3:-/home/romans/lampac/plugins/lampainit.js}"
POSTERS="${4:-/home/romans/poster-cache}"
SERVICE="${RECOMMENDER_SERVICE:-kinopoisk-sync}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
curl -fsSL --connect-timeout 5 --max-time 30 \
  "https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF/scripts/apply-profiles.py" -o "$WORK/apply.py"
if [[ -f "$POSTERS/.env" && -f "$POSTERS/install.py" ]]; then
  curl -fsSL --connect-timeout 5 --max-time 30 \
    "https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF/server/poster-cache/posters.js" -o "$WORK/posters.js"
fi
python3 "$WORK/apply.py" "$TARGET" "$LAMPAINIT" "$REF"
cd "$TARGET"
docker compose build "$SERVICE"
# Tests create temporary databases; the working profile and history are not modified.
docker compose run --rm --no-deps --entrypoint python "$SERVICE" -m unittest test_profiles
# Activate only after the new image has passed its profile tests.
docker compose up -d "$SERVICE"
docker compose exec -T "$SERVICE" python -c '
import time
from urllib.request import urlopen
for attempt in range(15):
    try:
        with urlopen("http://127.0.0.1:9120/profiles.json", timeout=3) as response:
            assert response.status == 200
        print("Сервер профилей готов")
        break
    except Exception:
        if attempt == 14: raise
        time.sleep(1)
'
if [[ -f "$WORK/posters.js" ]]; then
  cp -a "$POSTERS/posters.js" "$POSTERS/posters.js.before-profiles-$(date +%Y%m%d-%H%M%S)"
  cp "$WORK/posters.js" "$POSTERS/posters.js"
  (cd "$POSTERS" && python3 install.py)
fi
# Keep profile migration before the poster and catalog blocks at startup.
python3 install.py "$LAMPAINIT"
docker restart "${LAMPAC_CONTAINER:-lampac}"
echo 'Готово. На ПК Ctrl+F5; на ТВ полностью закройте и откройте Lampa.'
echo 'Первое открытие каждого старого устройства сохранит его историю в основном профиле.'

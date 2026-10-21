#!/usr/bin/env bash
# Install the existing catalog integration with header/rating/facts fixes.
set -euo pipefail
REF="${1:?Pass full HomeCinema commit SHA}"
TARGET="${2:-/home/romans/kinopoisk-sync}"
LAMPAINIT="${3:-/home/romans/lampac/plugins/lampainit.js}"
POSTERS="${4:-/home/romans/poster-cache}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
curl -fsSL --connect-timeout 5 --max-time 30 \
  "https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF/scripts/update-profiles.sh" -o "$WORK/update.sh"
bash "$WORK/update.sh" "$REF" "$TARGET" "$LAMPAINIT" "$POSTERS"
cd "$TARGET"
docker compose exec -T "${RECOMMENDER_SERVICE:-kinopoisk-sync}" python -c '
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:9120/facts/kp/1178445.json?type=tv",timeout=25) as response:
    result=json.load(response)
print("Фактов Кинопоиска для контрольной карточки:",len(result.get("items",[])))
if not result.get("items"):
    print(result.get("error") or "Страница доступна, но факты не извлечены; нужна проверка её разметки.")
'

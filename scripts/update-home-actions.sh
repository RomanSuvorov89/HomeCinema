#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:?Pass existing recommender directory}"
LAMPAINIT="${2:?Pass mounted lampainit.js path}"
REF="${3:?Pass full HomeCinema commit SHA}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
curl -fsSL --connect-timeout 5 --max-time 30 \
  "https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF/scripts/apply-home-actions.py" \
  -o "$WORK/apply.py"
python3 "$WORK/apply.py" "$TARGET" "$LAMPAINIT" "$REF"
cd "$TARGET"
docker compose up -d --build "${RECOMMENDER_SERVICE:-kinopoisk-sync}"
docker restart "${LAMPAC_CONTAINER:-lampac}"
echo 'Готово. Перезапустите Lampa на ТВ; в браузере Ctrl+F5.'

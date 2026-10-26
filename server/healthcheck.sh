#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
set -a
source .runtime.env
set +a

python3 ../scripts/check-lampa-web.py "http://127.0.0.1:${LAMPAC_PORT}" data/lampac/lampainit.js
curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${TORRSERVER_PORT}/" >/dev/null
curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${RECOMMENDER_PORT}/health" | python3 -m json.tool
curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${POSTER_PORT:-9121}/health" | python3 -m json.tool
echo "All server services are reachable"

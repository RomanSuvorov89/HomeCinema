#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
set -a
source .runtime.env
set +a

curl -fsS "http://127.0.0.1:${LAMPAC_PORT}/version?type=hash" >/dev/null
curl -fsS "http://127.0.0.1:${TORRSERVER_PORT}/" >/dev/null
curl -fsS "http://127.0.0.1:${RECOMMENDER_PORT}/health" | python3 -m json.tool
curl -fsS "http://127.0.0.1:${POSTER_PORT:-9121}/health" | python3 -m json.tool
echo "All server services are reachable"

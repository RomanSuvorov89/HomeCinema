#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
command -v docker >/dev/null
command -v python3 >/dev/null
command -v curl >/dev/null
docker compose version >/dev/null
if [[ ! -f .env ]]; then
    cp config.env.example .env
    printf '\nPUID=%s\nPGID=%s\n' "$(id -u)" "$(id -g)" >> .env
fi
setting() { python3 -c 'from install import config; import sys; print(config()[sys.argv[1]])' "$1"; }
base="$(setting POSTER_BASE)"
lampac="$(setting LAMPAC_URL)"
target="$(setting LAMPAINIT)"
test -w "$target"
mkdir -p data/posters
if [[ ! -f data/poster-overrides.json ]]; then
  cp ../../config/poster-overrides.example.json data/poster-overrides.json
fi
docker compose up -d --build
curl --fail --silent --show-error --retry 20 --retry-connrefused --retry-delay 1 --max-time 5 "$base/health"
printf '\nПроверка загрузки постера Эйфории...\n'
check_file="$(mktemp)"
trap 'rm -f "$check_file"' EXIT
if ! curl --fail --silent --show-error --max-time 25 "$base/poster/kp/1178445.jpg" -o "$check_file"; then
    printf 'Загрузка не прошла. Плагин НЕ подключён. Логи: docker logs --tail 40 roman-poster-cache\n' >&2
    exit 1
fi
python3 -c 'from server import image_type; import sys; print(image_type(open(sys.argv[1],"rb").read()))' "$check_file"
python3 install.py
docker restart lampac
curl --fail --silent --show-error --retry 30 --retry-connrefused --retry-delay 1 --max-time 5 "$lampac/lampainit.js" -o "$check_file"
python3 -c 'import sys; assert "/* roman-poster-cache:start */" in open(sys.argv[1]).read(), "Lampac did not serve the poster plugin"' "$check_file"
printf '\nГотово. Полностью закройте и откройте Lampa на ТВ; в браузере Ctrl+F5.\n'

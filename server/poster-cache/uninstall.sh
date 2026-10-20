#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 install.py --remove
docker restart lampac
docker compose down
printf 'Плагин отключён. Сохранённые изображения остались в data/posters.\n'

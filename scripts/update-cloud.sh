#!/usr/bin/env bash
set -euo pipefail
REF="${1:?Pass full HomeCinema commit SHA}"
[[ "$REF" =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
curl -fsSL --connect-timeout 5 --max-time 30 \
  "https://raw.githubusercontent.com/RomanSuvorov89/HomeCinema/$REF/scripts/update-profiles.sh" -o "$WORK/update.sh"
bash "$WORK/update.sh" "$@"
echo 'Облачное сохранение готово к настройке: R → Облачное сохранение → Подключить Яндекс Диск.'
echo 'ClientID и secret создаются один раз на oauth.yandex.ru; право: Доступ к папке приложения на Диске.'
echo 'Подключённый диск ничего не получает до выбора восстановления или начала нового сохранения.'

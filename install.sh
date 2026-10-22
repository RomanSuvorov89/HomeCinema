#!/usr/bin/env bash
# One-command entry point. This file also works when downloaded outside the repository.
set -euo pipefail
REPOSITORY='https://github.com/RomanSuvorov89/HomeCinema.git'
TARGET="${HC_INSTALL_DIR:-$HOME/HomeCinema}"
REF="${HC_REF:-main}"
[[ "$TARGET" == /* && "$TARGET" != / ]] || { echo 'HC_INSTALL_DIR must be an absolute directory'; exit 1; }
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ && "$REF" != -* ]] || { echo 'Invalid HC_REF'; exit 1; }
root_run() { if [[ "$(id -u)" == 0 ]]; then "$@"; else sudo "$@"; fi; }
if ! command -v git >/dev/null || ! command -v python3 >/dev/null || ! command -v curl >/dev/null; then
  if command -v apt-get >/dev/null; then
    root_run apt-get update
    root_run apt-get install -y git python3 curl ca-certificates
  elif command -v pacman >/dev/null; then
    root_run pacman -S --needed --noconfirm git python curl ca-certificates
  else
    echo 'Supported systems: Debian/Ubuntu and Arch/CachyOS. Install git, python3 and curl first.'; exit 1
  fi
fi
if [[ -e "$TARGET" ]]; then
  [[ -d "$TARGET/.git" ]] || { echo "Directory already exists and is not a checkout: $TARGET"; exit 1; }
  [[ "$(git -C "$TARGET" remote get-url origin)" == "$REPOSITORY" ]] || { echo 'Existing checkout belongs to another repository'; exit 1; }
  git -C "$TARGET" diff --quiet && git -C "$TARGET" diff --cached --quiet || {
    echo 'Tracked source files were changed. Existing work was preserved; choose another HC_INSTALL_DIR.'; exit 1;
  }
  echo "Continuing existing installation: $TARGET (without reset or automatic source update)"
else
  mkdir -p "$(dirname "$TARGET")"
  WORK="$(mktemp -d "${TARGET}.download.XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT
  git clone "$REPOSITORY" "$WORK"
  git -C "$WORK" checkout --detach "$REF"
  mv "$WORK" "$TARGET"
  trap - EXIT
fi
python3 "$TARGET/scripts/prepare-first-run.py" "$TARGET"
bash "$TARGET/server/install.sh" --install-deps
bash "$TARGET/server/healthcheck.sh"
echo
echo 'HomeCinema установлен. Откройте адрес из Installation completed на ПК или ТВ.'
echo 'На новой установке откроется меню Яндекс Диска. Подключите прежнее OAuth-приложение и выберите восстановление.'
echo 'Инструкция: https://github.com/RomanSuvorov89/HomeCinema/blob/main/docs/ONE_COMMAND.md'

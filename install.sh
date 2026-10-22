#!/usr/bin/env bash
# One-command entry point. This file also works when downloaded outside the repository.
set -euo pipefail
umask 077
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
  ORIGIN="$(git -C "$TARGET" config --get remote.origin.url)"
  [[ "${ORIGIN%.git}" == "${REPOSITORY%.git}" ]] || { echo 'Existing checkout belongs to another repository'; exit 1; }
  git -C "$TARGET" diff --quiet && git -C "$TARGET" diff --cached --quiet || {
    echo 'Tracked source files were changed. Existing work was preserved; choose another HC_INSTALL_DIR.'; exit 1;
  }
  git -C "$TARGET" fetch origin "$REF"
  CANDIDATE="$(git -C "$TARGET" rev-parse --verify FETCH_HEAD^{commit})"
  PREVIOUS="$(git -C "$TARGET" rev-parse --verify HEAD^{commit})"
  STAMP="$(date +%Y%m%d-%H%M%S)-$$"
  # Keep the prior source reachable even when switching detached commits.
  git -C "$TARGET" update-ref "refs/homecinema/backups/$STAMP" "$PREVIOUS"
  if [[ -f "$TARGET/server/.runtime.env" ]]; then
    if docker info >/dev/null 2>&1; then
      bash "$TARGET/server/backup.sh"
    else
      root_run bash "$TARGET/server/backup.sh"
    fi
  fi
  # No force/reset: Git also refuses untracked files that would be overwritten.
  git -C "$TARGET" checkout --detach "$CANDIDATE"
  echo "Updated source: $PREVIOUS -> $CANDIDATE; previous ref: refs/homecinema/backups/$STAMP"
else
  mkdir -p "$(dirname "$TARGET")"
  WORK="$(mktemp -d "${TARGET}.download.XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT
  git clone "$REPOSITORY" "$WORK"
  git -C "$WORK" checkout --detach "$REF"
  mv "$WORK" "$TARGET"
  trap - EXIT
fi
# Existing separate services are updated in place, never converted to the new stack.
LEGACY="${HC_LEGACY_DIR:-$HOME/kinopoisk-sync}"
CENTRAL="${HC_LAMPAINIT:-$HOME/lampac/plugins/lampainit.js}"
if [[ ! -f "$TARGET/config/stack.env" && -f "$LEGACY/kp_sync.py" && -f "$CENTRAL" ]]; then
  SHA="$(git -C "$TARGET" rev-parse --verify HEAD^{commit})"
  exec bash "$TARGET/scripts/update-profiles.sh" "$SHA" "$LEGACY" "$CENTRAL" "${HC_POSTER_DIR:-$HOME/poster-cache}"
fi
python3 "$TARGET/scripts/prepare-first-run.py" "$TARGET"
bash "$TARGET/server/install.sh" --install-deps
bash "$TARGET/server/healthcheck.sh"
echo
echo 'HomeCinema установлен или обновлён. Откройте адрес из Installation completed на ПК или ТВ.'
echo 'На новой установке откроется меню Яндекс Диска. Подключите прежнее OAuth-приложение и выберите восстановление.'
echo 'Инструкция: https://github.com/RomanSuvorov89/HomeCinema/blob/main/docs/ONE_COMMAND.md'

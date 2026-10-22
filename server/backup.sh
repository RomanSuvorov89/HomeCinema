#!/usr/bin/env bash
# Stop writers while archiving SQLite, including WAL sidecars; restore prior running services.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTINATION="${1:-$ROOT/backups}"
mkdir -p "$DESTINATION"
DESTINATION="$(cd "$DESTINATION" && pwd)"
case "$DESTINATION/" in "$ROOT/data/"*) echo 'Backup destination cannot be inside data'; exit 1;; esac
cd "$ROOT"
COMPOSE=(docker compose --env-file .runtime.env -f docker-compose.yml)
RUNNING_LINES="$("${COMPOSE[@]}" ps --status running --services)"
RUNNING=()
if [[ -n "$RUNNING_LINES" ]]; then mapfile -t RUNNING <<< "$RUNNING_LINES"; fi
restart_previous() { if ((${#RUNNING[@]})); then "${COMPOSE[@]}" start "${RUNNING[@]}"; fi; }
trap restart_previous EXIT
if ((${#RUNNING[@]})); then "${COMPOSE[@]}" stop "${RUNNING[@]}"; fi
STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$DESTINATION/home-cinema-backup-$STAMP.tar.gz"
tar -czf "$ARCHIVE.partial" --exclude='server/data/lampac/cache' -C "$ROOT/.." \
  VERSION server/.runtime.env server/data config/stack.env config/profiles.json config/rating-scale.json
mv "$ARCHIVE.partial" "$ARCHIVE"
chmod 600 "$ARCHIVE"
echo "$ARCHIVE"

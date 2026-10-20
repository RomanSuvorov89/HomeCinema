#!/usr/bin/env bash
# Export the existing containers without changing their deployment or writing into Git.
# Usage: bash scripts/export-current.sh /path/outside/repository
set -euo pipefail
DEST="${1:?Pass an empty destination outside the repository}"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$DEST/" in "$PROJECT/"*) echo 'Choose a destination outside this Git checkout'; exit 1;; esac
[[ -z "$(ls -A "$DEST")" ]] || { echo 'Destination must be empty'; exit 1; }
umask 077
LAMPAC_CONTAINER="${LAMPAC_CONTAINER:-lampac}"
RECOMMENDER_CONTAINER="${RECOMMENDER_CONTAINER:-kinopoisk-sync}"
POSTER_CONTAINER="${POSTER_CONTAINER:-roman-poster-cache}"
TORRSERVER_CONTAINER="${TORRSERVER_CONTAINER:-torrserver}"
CONTAINERS=("$LAMPAC_CONTAINER" "$RECOMMENDER_CONTAINER" "$POSTER_CONTAINER" "$TORRSERVER_CONTAINER")
# Validate every required mount before stopping anything.
for c in "${CONTAINERS[@]}"; do docker inspect "$c" >/dev/null; done
mapfile -t TORR_MOUNTS < <(docker inspect "$TORRSERVER_CONTAINER" --format '{{range .Mounts}}{{println .Destination}}{{end}}' | sed '/^$/d')
if [[ ! " ${TORR_MOUNTS[*]} " =~ ' /opt/ts ' ]]; then
  echo 'TorrServer must have its settings at /opt/ts. Inspect mounts and export them separately before migration.'
  exit 1
fi
RUNNING=()
for c in "${CONTAINERS[@]}"; do
  if [[ "$(docker inspect "$c" --format '{{.State.Running}}')" == true ]]; then RUNNING+=("$c"); fi
done
restart_previous() { if ((${#RUNNING[@]})); then docker start "${RUNNING[@]}" >/dev/null; fi; }
trap restart_previous EXIT
if ((${#RUNNING[@]})); then docker stop "${RUNNING[@]}" >/dev/null; fi
mkdir -p "$DEST/server/data/lampac" "$DEST/server/data/recommender" "$DEST/server/data/poster-cache" "$DEST/server/data/torrserver"
docker cp "$LAMPAC_CONTAINER:/lampac/database" "$DEST/server/data/lampac/"
docker cp "$LAMPAC_CONTAINER:/lampac/init.conf" "$DEST/server/data/lampac/"
docker cp "$LAMPAC_CONTAINER:/lampac/plugins/override/lampainit.js" "$DEST/lampainit.previous.js"
docker cp "$RECOMMENDER_CONTAINER:/data/." "$DEST/server/data/recommender/"
docker cp "$POSTER_CONTAINER:/data/." "$DEST/server/data/poster-cache/"
docker cp "$TORRSERVER_CONTAINER:/opt/ts/." "$DEST/server/data/torrserver/"
for c in "${CONTAINERS[@]}"; do
  docker inspect "$c" --format '{{.Name}} {{.Config.Image}} {{.Image}}' >> "$DEST/images.txt"
done
printf '%s\n' 'Export complete. Keep private. See docs/MIGRATION.md before restoration.' > "$DEST/README.txt"
echo "Export: $DEST"

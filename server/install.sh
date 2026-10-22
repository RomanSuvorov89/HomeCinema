#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$ROOT/../config"
ENV_FILE="$CONFIG_DIR/stack.env"
PROFILES_FILE="$CONFIG_DIR/profiles.json"

root_run() { if [[ "$(id -u)" == 0 ]]; then "$@"; else sudo "$@"; fi; }

install_dependencies() {
  if command -v pacman >/dev/null 2>&1; then
    root_run pacman -S --needed --noconfirm docker docker-compose curl jq python unzip
  elif command -v apt-get >/dev/null 2>&1; then
    root_run apt-get update
    root_run apt-get install -y docker.io curl jq python3 unzip
    root_run apt-get install -y docker-compose-v2 || \
      root_run apt-get install -y docker-compose-plugin || \
      root_run apt-get install -y docker-compose
  else
    echo "Automatic dependency installation supports Arch/CachyOS and Debian/Ubuntu only."
    exit 1
  fi
  root_run systemctl enable --now docker
  if [[ "$(id -u)" != 0 ]]; then root_run usermod -aG docker "$(id -un)"; fi
}

if [[ "${1:-}" == "--install-deps" ]]; then
  install_dependencies
fi

for command_name in docker curl jq python3; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing dependency: $command_name"
    echo "Run: ./install.sh --install-deps"
    exit 1
  }
done

if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
else
  DOCKER=(sudo docker)
fi

if "${DOCKER[@]}" compose version >/dev/null 2>&1; then
  COMPOSE=("${DOCKER[@]}" compose)
elif command -v docker-compose >/dev/null 2>&1; then
  if docker-compose version >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    COMPOSE=(sudo docker-compose)
  fi
else
  echo "Docker Compose is missing. Run: ./install.sh --install-deps"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$CONFIG_DIR/stack.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE. Edit it, then run the installer again."
  exit 2
fi

if [[ ! -f "$PROFILES_FILE" ]]; then
  cp "$CONFIG_DIR/profiles.example.json" "$PROFILES_FILE"
  echo "Created $PROFILES_FILE. Edit it, then run the installer again."
  exit 2
fi

if [[ ! -f "$CONFIG_DIR/rating-scale.json" ]]; then
  cp "$CONFIG_DIR/rating-scale.example.json" "$CONFIG_DIR/rating-scale.json"
fi

set -a
source "$ENV_FILE"
set +a

required=(STACK_NAME PUBLIC_LAMPAC_URL PUBLIC_TORRSERVER_URL PUBLIC_RECOMMENDER_URL PUBLIC_POSTER_URL LAMPAC_ROOT_PASSWORD ACTIVE_PROFILE_ID)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { echo "Missing $name in stack.env"; exit 1; }
done
[[ "$LAMPAC_ROOT_PASSWORD" != "CHANGE_ME" ]] || {
  echo "Change LAMPAC_ROOT_PASSWORD in stack.env"
  exit 1
}
[[ "$LAMPAC_ROOT_PASSWORD" =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo "LAMPAC_ROOT_PASSWORD may contain letters, digits and . _ - only"
  exit 1
}

PROFILE_JSON="$(jq -c --arg id "$ACTIVE_PROFILE_ID" '.profiles[] | select(.id == $id)' "$PROFILES_FILE")"
[[ -n "$PROFILE_JSON" ]] || { echo "Profile $ACTIVE_PROFILE_ID not found"; exit 1; }
KINOPOISK_PROFILE_ID="$(jq -r '.kinopoisk_profile_id' <<<"$PROFILE_JSON")"
PROFILE_DISPLAY_NAME="$(jq -r '.display_name' <<<"$PROFILE_JSON")"
HOME_PROFILE_ID="$(jq -r '.home_profile_id // .kinopoisk_profile_id' <<<"$PROFILE_JSON")"
LAMPAC_SYNC_ID="$(jq -r '.lampac_sync_id' <<<"$PROFILE_JSON")"
[[ "$HOME_PROFILE_ID" =~ ^([0-9]+|local_[a-f0-9]{24})$ ]] || { echo "Invalid initial home profile ID"; exit 1; }
[[ -z "$KINOPOISK_PROFILE_ID" || "$KINOPOISK_PROFILE_ID" =~ ^[0-9]+$ ]] || { echo "kinopoisk_profile_id must contain digits or be empty for a new home"; exit 1; }
[[ "$LAMPAC_SYNC_ID" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "lampac_sync_id contains unsupported characters"; exit 1; }
[[ "$PROFILE_DISPLAY_NAME" != *"'"* && "$PROFILE_DISPLAY_NAME" != *$'\n'* ]] || {
  echo "display_name may not contain apostrophes or newlines"
  exit 1
}

PUID="$(id -u)"
PGID="$(id -g)"
umask 077
cat > "$ROOT/.runtime.env" <<EOF
STACK_NAME=$STACK_NAME
TZ=${TZ:-Europe/Moscow}
LAMPAC_PORT=${LAMPAC_PORT:-9118}
TORRSERVER_PORT=${TORRSERVER_PORT:-8090}
RECOMMENDER_PORT=${RECOMMENDER_PORT:-9120}
POSTER_PORT=${POSTER_PORT:-9121}
PUID=$PUID
PGID=$PGID
KINOPOISK_PROFILE_ID=$KINOPOISK_PROFILE_ID
HOME_PROFILE_ID=$HOME_PROFILE_ID
PROFILE_DISPLAY_NAME='$PROFILE_DISPLAY_NAME'
LAMPAC_SYNC_ID=$LAMPAC_SYNC_ID
ENRICH_BATCH_SIZE=${ENRICH_BATCH_SIZE:-100}
ENRICH_WORKERS=${ENRICH_WORKERS:-10}
KINOPOISK_METADATA_RPM=${KINOPOISK_METADATA_RPM:-12}
WIKIPEDIA_METADATA_RPM=${WIKIPEDIA_METADATA_RPM:-20}
EOF

export KINOPOISK_PROFILE_ID HOME_PROFILE_ID PROFILE_DISPLAY_NAME LAMPAC_SYNC_ID PUID PGID
mkdir -p "$ROOT/data/lampac/cache" "$ROOT/data/lampac/database" "$ROOT/data/torrserver" "$ROOT/data/recommender" "$ROOT/data/poster-cache"
printf '%s' "$LAMPAC_ROOT_PASSWORD" > "$ROOT/data/lampac/passwd"
chmod 600 "$ROOT/data/lampac/passwd"

if [[ ! -f "$ROOT/data/lampac/init.conf" ]]; then
  cat > "$ROOT/data/lampac/init.conf" <<'JSON'
{
  "BaseModule": {"SkipModules": ["Catalog", "DLNA", "SISI", "TorrServer", "Tracks", "Transcoding", "WebLog"]},
  "gst": {"enable": true, "aac_channels": 2, "aac_bitrate": 256}
}
JSON
fi
if [[ ! -f "$ROOT/data/poster-cache/poster-overrides.json" ]]; then
  cp "$CONFIG_DIR/poster-overrides.example.json" "$ROOT/data/poster-cache/poster-overrides.json"
fi

python3 "$ROOT/../scripts/preflight-ports.py" "$ROOT" "${DOCKER[@]}"
"${DOCKER[@]}" pull ghcr.io/lampac-nextgen/lampac:latest
TEMP_CONTAINER="${STACK_NAME}-lampac-extract-$$"
"${DOCKER[@]}" create --name "$TEMP_CONTAINER" ghcr.io/lampac-nextgen/lampac:latest >/dev/null
trap '"${DOCKER[@]}" rm -f "$TEMP_CONTAINER" >/dev/null 2>&1 || true' EXIT
extracted=0
for source_path in /lampac/module/LampaWeb/plugins/lampainit.js /lampac/Modules/LampaWeb/plugins/lampainit.js; do
  if "${DOCKER[@]}" cp "$TEMP_CONTAINER:$source_path" "$ROOT/data/lampac/lampainit.upstream.js" 2>/dev/null; then
    extracted=1
    break
  fi
done
[[ "$extracted" == 1 ]] || { echo "Lampac layout changed: lampainit.js not found"; exit 1; }
"${DOCKER[@]}" rm "$TEMP_CONTAINER" >/dev/null
trap - EXIT

python3 "$ROOT/scripts/render.py"
"${COMPOSE[@]}" --env-file "$ROOT/.runtime.env" -f "$ROOT/docker-compose.yml" pull torrserver
"${COMPOSE[@]}" --env-file "$ROOT/.runtime.env" -f "$ROOT/docker-compose.yml" up -d --build

echo "Waiting for services..."
for _ in {1..60}; do
  if curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${LAMPAC_PORT:-9118}/version?type=hash" >/dev/null 2>&1 &&
     curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${RECOMMENDER_PORT:-9120}/health" >/dev/null 2>&1 &&
     curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:${POSTER_PORT:-9121}/health" >/dev/null 2>&1; then
    echo "Installation completed: $PUBLIC_LAMPAC_URL"
    exit 0
  fi
  sleep 2
done

echo "Containers started, but health check timed out."
"${COMPOSE[@]}" --env-file "$ROOT/.runtime.env" -f "$ROOT/docker-compose.yml" ps
exit 1

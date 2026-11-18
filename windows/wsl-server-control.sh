#!/usr/bin/env bash
set -euo pipefail
action=${1:-status}
repository=${2:-'~/HomeCinema'}
target=${3:-home-cinema-lampac}
case "$repository" in '~/'*) repository="$HOME/${repository:2}" ;; esac
cd -- "$repository"
compose=(docker compose --env-file server/.runtime.env -f server/docker-compose.yml)
case "$action" in
  status)
    printf 'Repository: %s\n\n' "$PWD"
    printf 'Docker: '
    docker info --format '{{.ServerVersion}}'
    printf '\nContainers (all projects, read only):\n'
    docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    ;;
  start) "${compose[@]}" up -d --no-build --pull never ;;
  stop) "${compose[@]}" stop ;;
  restart) "${compose[@]}" restart ;;
  health) bash server/healthcheck.sh ;;
  logs|restart-container)
    if [[ ! "$target" =~ ^home-cinema-[a-z0-9-]+$ ]]; then
      printf 'Only HomeCinema containers can be selected.\n' >&2; exit 2
    fi
    if [[ "$action" == logs ]]; then docker logs --timestamps --tail 150 "$target" 2>&1
    else docker restart "$target"; fi
    ;;
  resources) docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}' ;;
  disk) docker system df ;;
  *) printf 'Unknown action.\n' >&2; exit 2 ;;
esac

#!/usr/bin/env bash
set -euo pipefail
action=${1:-status}
target=${2:-}
case "$action" in
  status)
    printf 'Linux: '; uname -sr
    printf '\nUptime:\n'; uptime
    printf '\nMemory:\n'; free -h
    printf '\nRoot filesystem:\n'; df -h /
    printf '\nDocker:\n'
    if docker info --format '{{.ServerVersion}}'; then
      docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
      printf '\n__WSL_CONTAINER_NAMES__\n'
      docker ps -a --format '{{.Names}}'
    else
      printf 'Docker is unavailable; Linux is running.\n'
    fi
    ;;
  health)
    printf 'Failed Linux services:\n'; systemctl --failed --no-pager
    printf '\nDocker service:\n'; systemctl status docker --no-pager
    ;;
  logs|start-container|stop-container|restart-container)
    if [[ ! "$target" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]]; then
      printf 'Select a valid Docker container name.\n' >&2; exit 2
    fi
    docker inspect --type container "$target" >/dev/null
    case "$action" in
      logs) docker logs --timestamps --tail 150 "$target" 2>&1 ;;
      start-container) docker start "$target" ;;
      stop-container) docker stop "$target" ;;
      restart-container) docker restart "$target" ;;
    esac
    ;;
  resources) docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}' ;;
  disk) docker system df ;;
  linux-resources)
    uptime; free -h; df -h
    printf '\nProcesses by CPU:\n'
    ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -n 16 || true
    ;;
  *) printf 'Unknown action.\n' >&2; exit 2 ;;
esac

#!/bin/sh
# Read-only probes. No uci set/commit, restarts, routing edits or package installs.
set -u
hc_role=cachyos
if command -v uci >/dev/null 2>&1 && [ -f /etc/openwrt_release ]; then hc_role=openwrt; fi
printf '\n=== TMDB diagnostic: %s ===\n' "$hc_role"
date -u '+UTC %Y-%m-%d %H:%M:%S'
printf '\n=== Local hosts overrides for TMDB ===\n'
grep -Ei '(^|[[:space:]])([^[:space:]#]*\.)?(themoviedb\.org|tmdb\.org|tmdb-image-prod\.b-cdn\.net)([[:space:]]|$)' /etc/hosts 2>/dev/null || true
hc_bounded() {
    if command -v timeout >/dev/null 2>&1; then timeout 8 "$@"; else "$@"; fi
}
printf '\n=== System DNS ===\n'
for hc_host in www.themoviedb.org api.themoviedb.org image.tmdb.org; do
    printf '\n--- %s ---\n' "$hc_host"
    if command -v getent >/dev/null 2>&1; then
        hc_bounded getent ahostsv4 "$hc_host" || true
    else
        hc_bounded nslookup "$hc_host" || true
    fi
done
printf '\n=== Local listeners on web ports ===\n'
if command -v ss >/dev/null 2>&1; then
    ss -lntp 2>/dev/null | grep -E ':(80|443)[[:space:]]' || true
elif command -v netstat >/dev/null 2>&1; then
    netstat -lntp 2>/dev/null | grep -E ':(80|443)[[:space:]]' || true
fi
if command -v docker >/dev/null 2>&1; then
    printf '\n=== Containers publishing port 443 ===\n'
    hc_bounded docker ps --filter publish=443 --format '{{.Names}} {{.Ports}}' || true
fi
if [ "$hc_role" = openwrt ]; then
    printf '\n=== Router web listeners and existing VPN DNS settings ===\n'
    for hc_key in uhttpd.main.listen_http uhttpd.main.listen_https podkop.main.interface podkop.settings.dns_type podkop.settings.dns_server podkop.main.domain_resolver_enabled; do
        printf '%s: ' "$hc_key"
        uci -q get "$hc_key" || true
    done
fi
command -v curl >/dev/null 2>&1 || { echo 'curl is unavailable; no packages installed.'; exit 0; }
printf '\n=== DNS over HTTPS: default, no client subnet, Cloudflare ===\n'
for hc_host in image.tmdb.org api.themoviedb.org; do
    printf '\n--- %s / Google default ---\n' "$hc_host"
    curl --noproxy '*' -fsS --connect-timeout 3 --max-time 8 "https://dns.google/resolve?name=$hc_host&type=A" || true
    printf '\n--- %s / Google ECS disabled ---\n' "$hc_host"
    curl --noproxy '*' -fsS --connect-timeout 3 --max-time 8 "https://dns.google/resolve?name=$hc_host&type=A&edns_client_subnet=0.0.0.0%2F0" || true
    printf '\n--- %s / Cloudflare ---\n' "$hc_host"
    curl --noproxy '*' -fsS --connect-timeout 3 --max-time 8 -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=$hc_host&type=A" || true
    printf '\n'
done
printf '\n=== Local HTTP fingerprint with TMDB Host header (loopback only) ===\n'
# Header-only, no redirects followed, no authentication, no TLS bypass.
curl --noproxy '*' -sS --connect-timeout 2 --max-time 5 \
    --resolve www.themoviedb.org:80:127.0.0.1 -D - -o /dev/null \
    -w 'local-http: HTTP=%{http_code} PEER=%{remote_ip}\n' \
    http://www.themoviedb.org/ | grep -Ei '^(HTTP/|Server:|Location:|local-http:)' || true
printf '\n=== TLS comparison: system DNS versus explicit loopback ===\n'
for hc_mode in system loopback; do
    printf '\n--- %s ---\n' "$hc_mode"
    if [ "$hc_mode" = loopback ]; then
        curl --noproxy '*' -4 -sS --connect-timeout 2 --max-time 5 \
            --resolve api.themoviedb.org:443:127.0.0.1 -o /dev/null \
            -w 'HTTP=%{http_code} PEER=%{remote_ip} TLS_VERIFY=%{ssl_verify_result}\n' \
            https://api.themoviedb.org/3/configuration || true
    else
        curl --noproxy '*' -4 -sS --connect-timeout 2 --max-time 5 -o /dev/null \
            -w 'HTTP=%{http_code} PEER=%{remote_ip} TLS_VERIFY=%{ssl_verify_result}\n' \
            https://api.themoviedb.org/3/configuration || true
    fi
done
printf '\n=== End: no configuration changed ===\n'

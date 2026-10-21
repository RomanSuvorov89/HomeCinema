#!/bin/sh
# OpenWrt / ash. Reuse the existing VPN section; never replace its domain list.
set -eu
umask 077
hc_config=${HC_PODKOP_CONFIG:-/etc/config/podkop}
hc_init=${HC_PODKOP_INIT:-/etc/init.d/podkop}
hc_program=${HC_PODKOP_PROGRAM:-/usr/bin/podkop}
hc_backups=${HC_PODKOP_BACKUPS:-/root/homecinema-network-backups}
hc_lock=${HC_PODKOP_LOCK:-/tmp/homecinema-podkop-tmdb.lock}

if [ "${1:-}" = '--rollback' ]; then
    hc_saved=${2:?Pass the printed backup path}
    test -f "$hc_saved"
    cp "$hc_saved" "$hc_config"
    uci -q revert podkop
    "$hc_init" restart
    echo 'Настройки Podkop восстановлены из резервной копии.'
    exit 0
fi
hc_section=${1:-main}
case "$hc_section" in ''|*[!a-zA-Z0-9_]*) echo 'Invalid section name' >&2; exit 1;; esac
[ "$(uci -q get "podkop.$hc_section.connection_type")" = vpn ] || {
    echo 'Нужна существующая секция Podkop с connection_type=vpn.' >&2; exit 1;
}
[ -n "$(uci -q get "podkop.$hc_section.interface")" ]
[ -z "$(uci -q changes podkop)" ] || {
    echo 'В Podkop есть неприменённые изменения. Сначала сохраните или отмените их в LuCI.' >&2; exit 1;
}
grep -q 'domain_resolver_enabled' "$hc_program"
command -v sing-box >/dev/null
mkdir "$hc_lock" || { echo 'Другое обновление уже выполняется.' >&2; exit 1; }
hc_changed=0
hc_saved=''
hc_exit() {
    hc_status=$?
    trap - EXIT INT TERM
    if [ "$hc_changed" = 1 ]; then
        echo 'Обновление не завершилось; восстанавливаем прежние настройки.' >&2
        cp "$hc_saved" "$hc_config"
        uci -q revert podkop
        "$hc_init" restart || echo 'Не удалось перезапустить Podkop после отката.' >&2
    fi
    rmdir "$hc_lock"
    exit "$hc_status"
}
trap hc_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$hc_backups"
hc_saved="$hc_backups/podkop.before-tmdb-$(date +%Y%m%d-%H%M%S)-$$"
cp "$hc_config" "$hc_saved"
chmod 600 "$hc_saved"
echo "Резервная копия: $hc_saved"
printf 'Откат: sh %s --rollback %s\n' "$0" "$hc_saved"

hc_type=$(uci -q get "podkop.$hc_section.user_domain_list_type" || true)
hc_changed=1
case "$hc_type" in
    dynamic)
        hc_existing=$(uci -q get "podkop.$hc_section.user_domains" || true)
        for hc_domain in tmdb.org themoviedb.org tmdb-image-prod.b-cdn.net; do
            if ! printf '%s\n' "$hc_existing" | tr ' ' '\n' | grep -Fxq "$hc_domain"; then
                uci add_list "podkop.$hc_section.user_domains=$hc_domain"
            fi
        done
        ;;
    text|disabled|'')
        hc_text=$(uci -q get "podkop.$hc_section.user_domains_text" || true)
        for hc_domain in tmdb.org themoviedb.org tmdb-image-prod.b-cdn.net; do
            if ! printf '%s\n' "$hc_text" | sed 's#//.*##' | tr ', \t\r' '\n' | grep -Fxq "$hc_domain"; then
                hc_text="$hc_text
$hc_domain"
            fi
        done
        uci set "podkop.$hc_section.user_domains_text=$hc_text"
        uci set "podkop.$hc_section.user_domain_list_type=text"
        ;;
    *) echo 'Неизвестный тип списка доменов; обновление отменено.' >&2; exit 1;;
esac
# This resolver belongs to the selected VPN section. Its DoH traffic uses that
# section's VPN outbound in Podkop 0.7.22; global/bootstrap DNS are preserved.
uci set "podkop.$hc_section.domain_resolver_enabled=1"
uci set "podkop.$hc_section.domain_resolver_dns_type=doh"
uci set "podkop.$hc_section.domain_resolver_dns_server=1.1.1.1"
uci commit podkop
"$hc_init" restart
hc_generated=$(uci -q get podkop.settings.config_path || true)
[ -n "$hc_generated" ] || hc_generated=/etc/sing-box/config.json
sing-box check -c "$hc_generated"
hc_changed=0
echo 'Правила TMDB добавлены. DNS выбранной VPN-секции: Cloudflare DoH через VPN.'
echo 'Глобальный DNS, VPN-интерфейс и состояние mixed proxy сохранены.'
echo 'Перезапустите браузер/Lampa и проверьте загрузку. Работа сети ещё требует живой проверки.'

#!/usr/bin/env python3
"""Generate private first-run settings once. Existing configurations are never overwritten."""
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys


def detect_host():
    override = os.environ.get('HC_PUBLIC_HOST', '').strip()
    if override:
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', override) or '..' in override:
            raise ValueError('HC_PUBLIC_HOST: укажите IPv4 или DNS-имя без протокола/порта')
        return override
    # Ask the routing table only; UDP connect does not transmit any packet.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(('192.0.2.1', 9))
        routed = sock.getsockname()[0]
    candidates = []
    try:
        links = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'scope', 'global'], text=True))
        for link in links:
            if re.match(r'^(docker|veth|br-|tun|wg|awg|tailscale|virbr)', link['ifname']):
                continue
            for address in link.get('addr_info', []):
                ip = ipaddress.ip_address(address['local'])
                if ip.version == 4 and ip.is_private and not ip.is_loopback:
                    candidates.append(str(ip))
    except (OSError, ValueError, subprocess.CalledProcessError, KeyError):
        pass
    host = routed if routed in candidates or not candidates else candidates[0]
    if ipaddress.ip_address(host).is_loopback:
        raise ValueError('Не найден LAN-адрес; задайте HC_PUBLIC_HOST')
    return host


def private_write(path, text):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)


def prepare(root):
    root = Path(root)
    config = root / 'config'
    env, profiles = config / 'stack.env', config / 'profiles.json'
    if env.exists() or profiles.exists():
        if not env.is_file() or not profiles.is_file():
            raise ValueError('Неполная существующая конфигурация. Файлы сохранены; завершите настройку вручную.')
        print('Используем существующие настройки; пароли, адреса и профили не меняются')
        return
    host = detect_host()
    text = (config / 'stack.env.example').read_text()
    for key, port in [('PUBLIC_LAMPAC_URL', 9118), ('PUBLIC_TORRSERVER_URL', 8090),
                      ('PUBLIC_RECOMMENDER_URL', 9120), ('PUBLIC_POSTER_URL', 9121)]:
        text = re.sub(r'^' + key + r'=.*$', key + '=http://' + host + ':' + str(port), text, flags=re.M)
    text = text.replace('LAMPAC_ROOT_PASSWORD=CHANGE_ME', 'LAMPAC_ROOT_PASSWORD=' + secrets.token_hex(24))
    owner = 'local_' + secrets.token_hex(12)
    document = {'version': 1, 'active_profile': 'owner', 'profiles': [{
        'id': 'owner', 'display_name': 'Мой дом', 'home_profile_id': owner,
        'kinopoisk_profile_id': '', 'lampac_sync_id': secrets.token_hex(24)}]}
    private_write(profiles, json.dumps(document, ensure_ascii=False, indent=2) + '\n')
    try:
        private_write(env, text)
    except Exception:
        profiles.unlink()
        raise
    print('Созданы настройки нового дома: http://' + host + ':9118')
    print('ID Кинопоиска сейчас не нужен: восстановите облачную копию или подключите его в меню R')


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))

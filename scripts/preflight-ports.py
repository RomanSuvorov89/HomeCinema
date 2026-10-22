#!/usr/bin/env python3
"""Refuse port collisions with other stacks; never stop or remove their containers."""
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def owned_ports(root, docker):
    ids = subprocess.check_output(docker + ['ps', '-q'], text=True).split()
    result = set()
    for identity in ids:
        raw = subprocess.check_output(docker + ['inspect', '--format',
            '{"labels":{{json .Config.Labels}},"ports":{{json .NetworkSettings.Ports}}}', identity], text=True)
        item = json.loads(raw)
        labels = item.get('labels') or {}
        if labels.get('com.docker.compose.project') not in (os.environ['STACK_NAME'], root.name):
            continue
        workdir = labels.get('com.docker.compose.project.working_dir', '')
        if not workdir or Path(workdir).resolve() != root.resolve():
            continue
        for bindings in (item.get('ports') or {}).values():
            for binding in bindings or []:
                result.add(int(binding['HostPort']))
    return result


def check(root, docker):
    ports = [int(os.environ.get(key, default)) for key, default in (
        ('LAMPAC_PORT', 9118), ('TORRSERVER_PORT', 8090), ('RECOMMENDER_PORT', 9120), ('POSTER_PORT', 9121))]
    if len(set(ports)) != len(ports) or any(not 1024 <= p <= 65535 for p in ports):
        raise ValueError('Сервисам нужны разные порты от 1024 до 65535')
    own = owned_ports(root, docker)
    for port in ports:
        if port in own:
            continue
        for family, address in ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as sock:
                    if family == socket.AF_INET6:
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    sock.bind((address, port))
            except OSError as error:
                if family == socket.AF_INET6 and error.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                    continue
                if error.errno == errno.EADDRINUSE:
                    raise ValueError('Порт %s занят другим сервисом. Установка остановлена; существующие сервисы не менялись.' % port) from None
                raise


if __name__ == '__main__':
    try:
        check(Path(sys.argv[1]), sys.argv[2:] or ['docker'])
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))

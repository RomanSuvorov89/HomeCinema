#!/usr/bin/env python3
"""Install/remove the missing last-episode export trigger in the mounted lampainit."""
import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

BEGIN = '/* roman-family-watch:start */'
END = '/* roman-family-watch:end */'

SCRIPT = r"""
(function () {
    'use strict';
    if (window.romanFamilyWatchV1) return;
    window.romanFamilyWatchV1 = true;
    var host = __HOST__;
    var token = __TOKEN__;
    var timer = null;
    var busy = false;
    var dirty = false;
    var dirtyProfile = '';
    var attempts = 0;
    var fields = ['online_view', 'online_last_balanser', 'online_watched_last', 'torrents_view', 'torrents_filter_data'];

    function profile() { return String(Lampa.Storage.get('lampac_profile_id', '') || ''); }

    function schedule(delay) {
        clearTimeout(timer);
        timer = setTimeout(flush, delay);
    }

    function flush() {
        if (busy || !dirty || window.sync_disable) return;
        if (profile() !== dirtyProfile) { dirty = false; return; }
        var requestProfile = dirtyProfile;
        var value = {};
        fields.forEach(function (name) { value[name] = Lampa.Storage.get(name, ''); });
        var uri = host + '/storage/set?path=sync_view&pathfile=' + encodeURIComponent(requestProfile);
        var email = Lampa.Storage.get('account_email', '');
        var uid = Lampa.Storage.get('lampac_unic_id', '');
        if (email) uri += '&account_email=' + encodeURIComponent(email);
        if (uid) uri += '&uid=' + encodeURIComponent(uid);
        if (token) uri += '&token=' + encodeURIComponent(token);
        if (window.lwsEvent && window.lwsEvent.connectionId) uri += '&connectionId=' + encodeURIComponent(window.lwsEvent.connectionId);

        var xhr = new XMLHttpRequest();
        var finished = false;
        dirty = false;
        busy = true;
        function done(ok) {
            if (finished) return;
            finished = true;
            busy = false;
            if (ok) {
                attempts = 0;
                if (dirty) schedule(250);
            } else if (requestProfile === profile()) {
                dirty = true;
                attempts++;
                console.warn('Family Sync: last episode export failed, attempt ' + attempts);
                if (attempts < 4) schedule(attempts * 2000);
            } else if (dirty) schedule(250);
        }
        try {
            xhr.open('POST', uri, true);
            xhr.timeout = 10000;
            xhr.onload = function () {
                var result;
                try { result = JSON.parse(xhr.responseText); } catch (_) {}
                if (xhr.status === 200 && result && result.success && result.fileInfo) {
                    if (profile() === requestProfile) Lampa.Storage.set('lampac_sync_view', result.fileInfo.changeTime);
                    console.log('Family Sync: last episode saved');
                    done(true);
                } else done(false);
            };
            xhr.onerror = function () { done(false); };
            xhr.ontimeout = function () { done(false); };
            xhr.send(JSON.stringify(value));
        } catch (_) { done(false); }
    }

    var waits = 0;
    function start() {
        if (!window.Lampa || !Lampa.Storage || !Lampa.Storage.listener) {
            if (++waits < 300) setTimeout(start, 200);
            return;
        }
        Lampa.Storage.listener.follow('change', function (event) {
            if (event.name !== 'online_watched_last' || window.sync_disable) return;
            dirtyProfile = profile();
            dirty = true;
            attempts = 0;
            schedule(400);
        });
        // Do not export on startup: an old device must not seed stale progress.
    }
    start();
})();
"""


def update(path, host, token, remove=False):
    original = path.read_text(encoding='utf-8-sig')
    pattern = re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?'
    clean = re.sub(pattern, '', original, flags=re.S)
    if not remove and ('roman-family-sync' not in original or '/sync/js/' not in original):
        raise ValueError('Не найден установленный Family Sync; файл не изменён')
    script = SCRIPT.replace('__HOST__', json.dumps(host.rstrip('/'))).replace('__TOKEN__', json.dumps(token))
    updated = clean if remove else BEGIN + '\n' + script + '\n' + END + '\n' + clean
    if updated == original:
        print('Изменение уже установлено' if not remove else 'Обработчик уже удалён')
        return
    backup = path.with_name(path.name + '.before-family-watch-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(path, backup)
    with path.open('w', encoding='utf-8') as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    print('Резервная копия:', backup)
    print('Обработчик последней серии ' + ('удалён' if remove else 'установлен'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--remove', action='store_true', help='Удалить только этот обработчик, оставив остальные плагины')
    args = parser.parse_args()
    host = urlsplit(args.host)
    if host.scheme not in ('http', 'https') or not host.hostname or host.query or host.fragment:
        parser.error('Неверный --host')
    update(args.path, args.host, args.token, args.remove)

#!/usr/bin/env python3
"""Install central client defaults before Lampa creates the first Activity."""
from datetime import datetime
from pathlib import Path
import re
import shutil
import sys


def install(target):
    original = target.read_text(encoding='utf-8')
    text = original
    marker = '/* roman-kinopoisk-local */'
    anchor = 'var plugins_add = {initiale};'
    if not re.search(r'function\s+start\s*\(\s*\)\s*\{', text):
        raise ValueError('Не найден start(): файл не изменён')
    root = Path(__file__).resolve().parent
    for name in ('client-defaults', 'bootstrap'):
        pattern = r'/\* roman-' + name + r'-start \*/.*?/\* roman-' + name + r'-end \*/\n?'
        text = re.sub(pattern, '', text, flags=re.S)
    payload = []
    for name in ('client-defaults.js', 'kinopoisk.js', 'track-memory.js'):
        body = (root / name).read_text(encoding='utf-8')
        payload.append("try {\n" + body + "\n} catch(e) {report('" + name + "',e.stack || e.message);}")
        if name == 'kinopoisk.js':
            payload.append('window.romanEmbedded054 = !!window.romanKinopoiskStarted;')
    bootstrap = (root / 'client-bootstrap.js').read_text(encoding='utf-8').replace('/* ROMAN_EMBEDDED_PAYLOAD */', '\n'.join(payload))
    block = '/* roman-bootstrap-start */\n' + bootstrap + '\n/* roman-bootstrap-end */\n'
    if marker not in text:
        if anchor not in text:
            raise ValueError('Не найден plugins_add: файл не изменён')
        match = re.search(r"var DATA_URL\s*=\s*'([^']+)/data.json'", (root / 'kinopoisk.js').read_text())
        if not match:
            raise ValueError('Run portable renderer before installing this client')
        plugin_url = match.group(1) + '/kinopoisk.js'
        text = text.replace(anchor, anchor + '''
    /* roman-kinopoisk-local */
    plugins_add.push({name: "Кинопоиск (локальный)",
      url: "http://127.0.0.1:9120/kinopoisk.js", status: 1});
'''.replace('http://127.0.0.1:9120/kinopoisk.js', plugin_url), 1)
    text = block + text
    profile_script = root / 'profiles-client.js'
    if profile_script.is_file():
        text = re.sub(r'/\* homecinema-profiles:start \*/.*?/\* homecinema-profiles:end \*/\n?', '', text, flags=re.S)
        text = '/* homecinema-profiles:start */\n' + profile_script.read_text() + '\n/* homecinema-profiles:end */\n' + text
    if text == original:
        print('Центральные настройки уже актуальны')
        return
    backup = target.with_name('lampainit.js.before-tv-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(target, backup)
    # Preserve the existing inode: lampainit can itself be a Docker bind mount.
    target.write_text(text, encoding='utf-8')
    print('Обновлены центральные настройки CUB/Android и подключение плагина')
    print('Backup:', backup)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 install.py /path/to/lampainit.js (run portable renderer first)')
    install(Path(sys.argv[1]))

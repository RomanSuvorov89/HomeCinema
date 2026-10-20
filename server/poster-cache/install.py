#!/usr/bin/env python3
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
BEGIN = '/* roman-poster-cache:start */'
END = '/* roman-poster-cache:end */'


def config():
    result = {}
    for line in (ROOT / '.env').read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            result[key] = value.strip()
    return result


def install():
    cfg = config()
    target = Path(cfg['LAMPAINIT'])
    original = target.read_text(encoding='utf-8-sig')
    base = cfg['POSTER_BASE'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError('Invalid POSTER_BASE')
    script = (ROOT / 'posters.js').read_text().replace("'__POSTER_BASE__'", json.dumps(base))
    pattern = re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?'
    clean = re.sub(pattern, '', original, flags=re.S)
    updated = BEGIN + '\n' + script + '\n' + END + '\n' + clean
    if updated == original:
        print('Poster plugin already installed')
        return
    backup = target.with_name(target.name + '.before-posters-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(target, backup)
    # Retain the inode because this file is mounted directly into Docker.
    with target.open('w', encoding='utf-8') as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    print('Backup:', backup)
    print('Installed:', target)


if __name__ == '__main__':
    import sys
    if '--remove' in sys.argv:
        target = Path(config()['LAMPAINIT'])
        text = target.read_text(encoding='utf-8')
        updated = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.S)
        if updated != text:
            shutil.copy2(target, target.with_name(target.name + '.before-remove-posters-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
            target.write_text(updated, encoding='utf-8')
        print('Removed only the poster plugin block')
    else:
        install()

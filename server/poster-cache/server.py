#!/usr/bin/env python3
"""Disk-backed Kinopoisk posters. Catalog databases are read only."""
from datetime import date
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from kinoafisha_posters import KinoafishaPosters
from urllib.request import urlopen

CACHE = Path(os.environ.get('POSTER_CACHE', '/data/posters'))
CATALOG = Path(os.environ.get('CATALOG_DIR', '/catalog'))
LAMPAC = os.environ.get('LAMPAC_URL', 'http://127.0.0.1:9118').rstrip('/')
FAMILY = os.environ.get('FAMILY_TOKEN', 'home-family')
MAX_BYTES = 8 * 1024 * 1024


def image_type(data):
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n') and b'IEND' in data[-20:]:
        return 'image/png'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP' and int.from_bytes(data[4:8], 'little') + 8 == len(data):
        return 'image/webp'
    raise ValueError('Upstream response is not a complete JPEG, PNG or WebP')


def valid_id(value):
    value = str(value or '')
    return value if re.fullmatch(r'[1-9][0-9]{0,9}', value) else None


class Posters:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.locks = [threading.Lock() for _ in range(64)]
        self.slots = threading.BoundedSemaphore(3)
        self.failures = {}
        self.state_lock = threading.Lock()
        self.kinoafisha = KinoafishaPosters(CATALOG)

    def fetch(self, kp_id):
        source = 'https://st.kp.yandex.net/images/film_iphone/iphone360_' + kp_id + '.jpg'
        return self.download(source)

    def download(self, source):
        with self.slots:
            fd, temporary = tempfile.mkstemp(prefix='download-', dir=self.root)
            os.close(fd)
            try:
                result = subprocess.run([
                    'curl', '--fail', '--silent', '--show-error', '--location',
                    '--proto', '=https', '--proto-redir', '=https', '--max-redirs', '4',
                    '--connect-timeout', '4', '--max-time', '12',
                    '--max-filesize', str(MAX_BYTES), '--output', temporary, source,
                ], capture_output=True, timeout=15)
                if result.returncode:
                    raise OSError(result.stderr.decode(errors='replace')[-300:])
                data = Path(temporary).read_bytes()
                if not 128 <= len(data) <= MAX_BYTES:
                    raise ValueError('Invalid image size')
                image_type(data)
                return data
            finally:
                Path(temporary).unlink(missing_ok=True)

    def get(self, kp_id, season=0):
        if not isinstance(season, int) or not 0 <= season <= 999:
            raise ValueError('Invalid season')
        kp_id = valid_id(kp_id)
        if not kp_id:
            raise ValueError('Invalid Kinopoisk ID')
        overrides_file = self.root.parent / 'poster-overrides.json'
        if overrides_file.exists():
            overrides = json.loads(overrides_file.read_text())
            kp_id = valid_id(overrides.get(kp_id, kp_id))
            if not kp_id:
                raise ValueError('Invalid poster override')
        key = kp_id + '.v3.s' + str(season)
        path = self.root / (key + '.img')
        metadata = self.root / (key + '.json')
        with self.locks[int(kp_id) % len(self.locks)]:
            stale = None
            if path.is_file():
                data = path.read_bytes()
                stale = (data, image_type(data), True)
                info = json.loads(metadata.read_text()) if metadata.is_file() else {}
                ttl = 86400 if info.get('source', '').startswith('kinoafisha') else 21600
                if time.time() - path.stat().st_mtime < ttl:
                    return stale
            with self.state_lock:
                if self.failures.get(key, 0) > time.monotonic():
                    if stale:
                        return stale
                    raise OSError('Previous download failed; retry after 60 seconds')
            try:
                source = 'kinopoisk'
                data = None
                try:
                    sources = self.kinoafisha.sources(kp_id, season)
                except Exception as error:
                    sources = []
                    print('kinoafisha fallback:', kp_id, str(error)[-200:], flush=True)
                for candidate, url in sources:
                    try:
                        data = self.download(url)
                        source = candidate
                        break
                    except Exception as error:
                        print('poster source failed:', candidate, str(error)[-160:], flush=True)
                if data is None:
                    legacy = self.root / (kp_id + '.img')
                    if legacy.is_file():
                        data = legacy.read_bytes()
                        image_type(data)
                    else:
                        data = self.fetch(kp_id)
                fd, temporary = tempfile.mkstemp(prefix='save-', dir=self.root)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
                metadata.write_text(json.dumps({'source': source, 'season': season, 'checked_at': int(time.time())}))
                print('poster saved:', kp_id, 'season:', season, 'source:', source, len(data), flush=True)
                return data, image_type(data), False
            except Exception:
                with self.state_lock:
                    self.failures[key] = time.monotonic() + 60
                    if len(self.failures) > 4096:
                        now = time.monotonic()
                        self.failures = {k: v for k, v in self.failures.items() if v > now}
                if stale:
                    return stale
                raise


class Catalog:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = {'paths': {}, 'ids': {}, 'imdb': {}, 'seasons': {}, 'errors': [], 'updated_at': 0}

    def snapshot(self):
        with self.lock:
            return self.value

    def refresh(self):
        index = {'paths': {}, 'ids': {}, 'imdb': {}, 'seasons': {}, 'errors': [], 'updated_at': int(time.time())}
        conflicts = {key: set() for key in ('paths', 'ids', 'imdb')}

        def put(group, key, kp):
            if not key or key in conflicts[group]:
                return
            old = index[group].get(key)
            if old and old != kp:
                index[group].pop(key, None)
                conflicts[group].add(key)
            else:
                index[group][key] = kp

        def card(c):
            if not isinstance(c, dict):
                return
            kp = valid_id(c.get('kinopoisk_id') or c.get('kp_id'))
            if not kp:
                return
            kind = c.get('media_type') or ('tv' if c.get('name') or c.get('first_air_date') else 'movie')
            tmdb = c.get('tmdb_id')
            if not tmdb and c.get('source', 'tmdb') in ('tmdb', 'cub'):
                tmdb = c.get('id')
            if valid_id(tmdb) and kind in ('movie', 'tv'):
                put('ids', kind + ':' + str(tmdb), kp)
            if re.fullmatch(r'tt[0-9]+', str(c.get('imdb_id', ''))):
                put('imdb', c['imdb_id'], kp)
            poster = c.get('poster_path')
            if isinstance(poster, str) and poster.startswith('/'):
                put('paths', poster.lstrip('/'), kp)

        for name, query, transform in [
            ('recommender.sqlite3', 'SELECT kp_id,tmdb_id,imdb_id,media_type,poster_path FROM media', dict),
            ('home-cache.sqlite3', 'SELECT payload_json FROM cards', lambda r: json.loads(r['payload_json'])),
        ]:
            path = CATALOG / name
            if not path.exists():
                continue
            try:
                with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
                    conn.row_factory = sqlite3.Row
                    for row in conn.execute(query):
                        card(transform(row))
            except Exception as error:
                index['errors'].append(name + ': ' + str(error))

        # Last aired season is a fallback; the client can request its watched season.
        database = CATALOG / 'recommender.sqlite3'
        if database.is_file():
            try:
                with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='episode_schedules'").fetchone():
                        today = date.today().isoformat()
                        for kp, payload in conn.execute('SELECT kp_id,episodes_json FROM episode_schedules'):
                            try:
                                aired = [int(e['season']) for e in json.loads(payload or '[]')
                                         if e.get('date') and e['date'] <= today and 0 < int(e.get('season', 0)) <= 999]
                                if aired:
                                    index['seasons'][str(kp)] = max(aired)
                            except (ValueError, TypeError, KeyError):
                                pass
            except Exception as error:
                index['errors'].append('seasons: ' + str(error))

        try:
            from urllib.parse import urlencode
            with urlopen(LAMPAC + '/bookmark/list?' + urlencode({'token': FAMILY}), timeout=5) as response:
                bookmarks = json.load(response)
            for c in bookmarks.get('card', []):
                card(c)
        except Exception as error:
            index['errors'].append('bookmarks: ' + str(error))
        # A transient catalog failure must not erase confirmed mappings.
        with self.lock:
            if index['errors']:
                for group in ('paths', 'ids', 'imdb'):
                    index[group] = dict(self.value[group], **index[group])
            for group in conflicts:
                for key in conflicts[group]:
                    index[group].pop(key, None)
            self.value = index

    def run(self):
        while True:
            try:
                self.refresh()
            except Exception as error:
                print('catalog error:', error, flush=True)
            time.sleep(60)


POSTERS = None
CATALOG_INDEX = Catalog()


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type, cache='no-store', etag=None):
        if etag and self.headers.get('If-None-Match') == etag:
            code, body = 304, b''
        self.send_response(code)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        if etag:
            self.send_header('ETag', etag)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'If-None-Match')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            payload = {'ok': True, 'version': '0.2.0', 'saved': len(list(POSTERS.root.glob('*.img'))),
                       'catalog_errors': CATALOG_INDEX.snapshot()['errors']}
            self.send(200, json.dumps(payload).encode(), 'application/json')
        elif path == '/index.json':
            self.send(200, json.dumps(CATALOG_INDEX.snapshot()).encode(), 'application/json')
        elif re.fullmatch(r'/poster/kp/[1-9][0-9]{0,9}\.jpg', path):
            try:
                query = parse_qs(urlsplit(self.path).query)
                season = int(query.get('season', ['0'])[0])
                data, mime, cached = POSTERS.get(path.rsplit('/', 1)[1][:-4], season)
                self.send(200, data, mime, 'public, max-age=3600', '"' + hashlib.sha256(data).hexdigest() + '"')
            except Exception as error:
                print('poster error:', path, str(error), flush=True)
                self.send(502, b'Poster unavailable; retry later', 'text/plain')
        else:
            self.send(404, b'Not found', 'text/plain')


if __name__ == '__main__':
    POSTERS = Posters(CACHE)
    threading.Thread(target=CATALOG_INDEX.run, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 9121), Handler).serve_forever()

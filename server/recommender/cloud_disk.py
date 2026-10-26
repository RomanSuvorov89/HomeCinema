"""Encrypted, immutable Yandex Disk backups. No hosted relay or inbound port required."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zlib

MAGIC = b'HCLOUD1\0'
AUTO_MAGIC = b'HCLOUD2\0'
LIMIT = 64 * 1024 * 1024
ROOT = 'app:/HomeCinema'
TABLES = ('profiles', 'rating_scale', 'media', 'user_ratings', 'watchlist', 'features',
          'media_features', 'profile_feature_stats', 'candidate_catalog', 'candidate_scores',
          'mapping_review', 'series_tracking', 'episode_schedule_links', 'episode_schedule_versions',
          'episode_schedules', 'prediction_calibration', 'recommendation_feedback', 'track_preferences',
          'home_profiles', 'home_profile_state', 'home_profile_backups', 'home_connections')
DEVICE_FIELDS = {'torrserver_url', 'torrserver_use_link', 'torrserver_auth', 'torrserver_login',
                 'torrserver_password', 'jackett_url', 'jackett_key', 'parser_use', 'parser_torrent_type',
                 'player_volume', 'interface_sound_level', 'video_quality_default', 'player_normalization',
                 'player_subs_shift_time', 'subtitles_start', 'homecinema_appearance', 'poster_size'}


class CloudError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(url, method='GET', data=None, headers=None, binary=False, _redirects=0):
    # Signed Disk URLs must stay HTTPS. Never send OAuth headers to arbitrary hosts.
    parsed = urlparse(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or not any(host == d or host.endswith('.' + d)
            for d in ('yandex.ru', 'yandex.net', 'yandex.com')) or parsed.port not in (None, 443):
        raise CloudError('Недопустимый адрес Яндекс Диска')
    req = Request(url, data=data, method=method, headers=headers or {})
    try:
        with build_opener(NoRedirect()).open(req, timeout=25) as response:
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise CloudError('Копия превышает 64 МБ')
            return raw if binary else json.loads(raw or b'{}')
    except HTTPError as error:
        if binary and error.code in (301, 302, 303, 307, 308) and (method == 'GET' or error.code in (307, 308)):
            if _redirects >= 3:
                raise CloudError('Слишком много перенаправлений Яндекс Диска') from None
            target = urljoin(url, error.headers.get('Location', ''))
            forwarded = dict(headers or {})
            if urlparse(target).hostname != host:
                forwarded = {k: v for k, v in forwarded.items() if k.lower() != 'authorization'}
            # Each new address is validated again; credentials never follow a host change.
            return http(target, method, data, forwarded, binary=True, _redirects=_redirects + 1)
        # Provider errors are intentionally not logged: URLs/bodies can contain credentials.
        if host.startswith('oauth.'):
            try:
                result = json.loads(error.read(8192))
                return {'error': result.get('error', 'oauth_error')}
            except (ValueError, TypeError):
                pass
        raise CloudError('Яндекс Диск: HTTP ' + str(error.code)) from None
    except (URLError, TimeoutError, OSError):
        raise CloudError('Нет связи с Яндекс Диском; повторим позже') from None


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()


def derive(password, salt):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise CloudError('Пароль копий: от 12 до 256 символов. Сохраните его отдельно.')
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=64*1024*1024)


def encrypt(document, key, salt, magic=MAGIC):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    header = magic + salt + nonce
    raw = json_bytes(document)
    if len(raw) > LIMIT:
        raise CloudError('Снимок превышает 64 МБ')
    return header + AESGCM(key).encrypt(nonce, zlib.compress(raw), header)


def decrypt(raw, password=None, *, auto_key=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(raw) > LIMIT or len(raw) < 52 or raw[:8] not in (MAGIC, AUTO_MAGIC):
        raise CloudError('Неизвестный формат копии')
    salt, nonce = raw[8:24], raw[24:36]
    key = auto_key if raw[:8] == AUTO_MAGIC else derive(password, salt)
    if not isinstance(key, bytes) or len(key) != 32:
        raise CloudError('Не удалось получить ключ копии с Яндекс Диска')
    try:
        packed = AESGCM(key).decrypt(nonce, raw[36:], raw[:36])
        stream = zlib.decompressobj()
        decoded = stream.decompress(packed, LIMIT + 1)
        if len(decoded) > LIMIT or not stream.eof or stream.unused_data:
            raise ValueError('size')
        result = json.loads(decoded)
        if result.get('version') != 1 or not isinstance(result.get('tables'), dict):
            raise ValueError('format')
        return result, key, salt
    except Exception:
        raise CloudError('Неверный пароль или повреждённая копия') from None


def valid_devices(value):
    if not isinstance(value, dict) or len(value) > 100 or len(json_bytes(value)) > 1024 * 1024:
        raise CloudError('Неверные настройки устройств в копии')
    for device, row in value.items():
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}', str(device)) or not isinstance(row, dict):
            raise CloudError('Неверное устройство в копии')
        values = row.get('values')
        if not isinstance(row.get('updated_at'), int) or not isinstance(values, dict) or set(values) - DEVICE_FIELDS:
            raise CloudError('Неверные поля устройства в копии')
        if any(not isinstance(v, (str, int, float, bool, type(None))) for v in values.values()):
            raise CloudError('Неверные значения устройства в копии')
    return value


def snapshot(factory, owner, devices):
    c = factory()
    try:
        from connections import ensure
        ensure(c)
        # Preserve the legacy implicit KP source even when owner IDs change on a new server.
        if owner.isdigit():
            with c:
                c.execute('INSERT OR IGNORE INTO home_connections(profile_id,kp_id) VALUES(?,?)', (owner, owner))
        c.execute('BEGIN')  # One consistent WAL read snapshot, including all personal tables.
        existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables = {}
        for name in TABLES:
            if name in existing:
                columns = [r[1] for r in c.execute('PRAGMA table_info("' + name + '")')]
                tables[name] = {'columns': columns, 'rows': [list(r) for r in c.execute('SELECT * FROM "' + name + '"')]}
        return {'version': 1, 'owner': owner, 'created_at': int(time.time()), 'tables': tables,
                'devices': devices}
    finally:
        c.close()


def restore(factory, document, owner, backup_dir):
    tables = document.get('tables', {})
    if set(tables) - set(TABLES) or not {'profiles', 'home_profile_state', 'home_profiles'} <= set(tables):
        raise CloudError('Копия не содержит профилей или имеет неподдерживаемую структуру')
    c = factory()
    try:
        # Optional tables are created from installed code, never from archive SQL.
        from episode_schedule import SCHEMA
        from candidate_engine import candidate_schema_sql
        from track_preferences import ensure as tracks_ensure
        from review_api import ensure_schema
        from connections import ensure as connections_ensure
        c.executescript(SCHEMA)
        c.executescript(candidate_schema_sql())
        tracks_ensure(c)
        ensure_schema(c)
        connections_ensure(c)
        # Archive columns/SQL are never executed. Only known local schema names are used.
        prepared, restore_columns = {}, {}
        for name, table in tables.items():
            columns = [r[1] for r in c.execute('PRAGMA table_info("' + name + '")')]
            incoming = table.get('columns')
            if not isinstance(incoming, list) or any(not isinstance(v, str) for v in incoming):
                raise CloudError('Неверные столбцы копии: ' + name)
            if not columns or len(incoming) != len(set(incoming)) or set(incoming) != set(columns):
                missing = ', '.join(sorted(set(columns) - set(incoming)))
                extra = ', '.join(sorted(set(incoming) - set(columns)))
                raise CloudError('Несовместимая структура базы: ' + name +
                    ('; отсутствуют в копии: ' + missing if missing else '') +
                    ('; неизвестны на сервере: ' + extra if extra else ''))
            restore_columns[name] = columns
            positions = [incoming.index(column) for column in columns]
            rows = table.get('rows')
            if not isinstance(rows, list) or any(not isinstance(r, list) or len(r) != len(columns)
                    or any(not isinstance(v, (str, int, float, type(None))) for v in r) for r in rows):
                raise CloudError('Неверные строки копии')
            prepared[name] = [[r[i] for i in positions] for r in rows]
            if 'profile_id' in columns:
                index = columns.index('profile_id')
                for row in prepared[name]:
                    if row[index] == document['owner']:
                        row[index] = owner
        ids = [r[restore_columns['profiles'].index('profile_id')] for r in prepared['profiles']]
        if owner not in ids or len(ids) != len(set(ids)):
            raise CloudError('Конфликт идентификаторов профилей')
        # Save a full local SQLite backup BEFORE any destructive operation.
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest = backup_dir / ('before-cloud-' + str(time.time_ns()) + '.sqlite3')
        fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(dest) as backup:
            c.backup(backup)
        c.execute('BEGIN IMMEDIATE')
        c.execute('PRAGMA defer_foreign_keys=ON')
        for name in reversed(TABLES):
            if name in prepared:
                c.execute('DELETE FROM "' + name + '"')
        for name in TABLES:
            if name in prepared:
                marks = ','.join('?' for _ in restore_columns[name])
                names = ','.join('"' + column + '"' for column in restore_columns[name])
                c.executemany('INSERT INTO "' + name + '" (' + names + ') VALUES(' + marks + ')', prepared[name])
        c.execute('CREATE TABLE IF NOT EXISTS home_restore_meta(epoch TEXT NOT NULL)')
        c.execute('DELETE FROM home_restore_meta')
        c.execute('INSERT INTO home_restore_meta VALUES(?)', (secrets.token_hex(16),))
        if c.execute('PRAGMA foreign_key_check').fetchone():
            raise CloudError('Копия содержит нарушенные связи; восстановление отменено')
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


class Manager:
    def __init__(self, root, factory, owner, transport=http):
        self.root, self.factory, self.owner = Path(root), factory, owner
        self.transport = transport
        self.lock = threading.RLock()
        self.pending = None
        self.staged = None
        self.job = False
        self.last_error = ''
        self.config = self.read('connection.json', {})
        self.devices = self.read('devices.json', {})
        self.last_save = 0
        self.digest = ''

    def read(self, name, default):
        try:
            return json.loads((self.root / name).read_text())
        except FileNotFoundError:
            return default

    def write(self):
        private_write(self.root / 'connection.json', json_bytes(self.config))

    def oauth(self, endpoint, values):
        return self.transport('https://oauth.yandex.ru/' + endpoint, 'POST', urlencode(values).encode(),
                              {'Content-Type': 'application/x-www-form-urlencoded'})

    def status(self):
        return {'needs_setup': self.owner.startswith('local_') and not self.config.get('enabled', False),
                    'configured': bool(self.config.get('client_id')), 'connected': bool(self.config.get('access_token')),
                    'enabled': self.config.get('enabled', False), 'busy': self.job,
                    'last_save': self.config.get('last_save', 0), 'error': self.last_error,
                    'awaiting_choice': bool(self.config.get('access_token')) and not self.config.get('enabled', False)}

    def start(self, payload):
        client = str(payload.get('client_id', self.config.get('client_id', '')))
        secret = str(payload.get('client_secret', self.config.get('client_secret', '')))
        if not re.fullmatch('[a-fA-F0-9]{32}', client) or not 16 <= len(secret) <= 256:
            raise CloudError('Введите ClientID и Client secret своего OAuth-приложения Яндекса')
        result = self.oauth('device/code', {'client_id': client, 'device_id': self.config.get('instance', secrets.token_hex(16)),
                                          'device_name': 'HomeCinema'})
        if result.get('error'):
            raise CloudError('Яндекс не разрешил вход: ' + result['error'])
        self.config.update(client_id=client, client_secret=secret, enabled=False)
        for field in ('access_token', 'refresh_token', 'expires'):
            self.config.pop(field, None)
        self.config.setdefault('instance', secrets.token_hex(16))
        self.pending = {'code': result['device_code'], 'expires': time.time() + result['expires_in'],
                        'interval': max(5, result['interval']), 'next': 0}
        self.write()
        return {k: result[k] for k in ('user_code', 'verification_url', 'expires_in', 'interval')}

    def poll(self):
        with self.lock:
            if not self.pending or time.time() > self.pending['expires']:
                self.pending = None
                raise CloudError('Код истёк. Запросите новый.')
            if time.time() < self.pending['next']:
                return {'pending': True}
            self.pending['next'] = time.time() + self.pending['interval']
            result = self.oauth('token', {'grant_type': 'device_code', 'code': self.pending['code'],
                'client_id': self.config['client_id'], 'client_secret': self.config['client_secret']})
            error = result.get('error')
            if error in ('authorization_pending', 'slow_down'):
                if error == 'slow_down':
                    self.pending['interval'] += 5
                return {'pending': True}
            if error:
                self.pending = None
                raise CloudError('Вход не завершён: ' + error)
            self.set_token(result)
            self.pending = None
            return {'connected': True}

    def set_token(self, result):
        self.config['access_token'] = result['access_token']
        if result.get('refresh_token'):
            self.config['refresh_token'] = result['refresh_token']
        self.config['expires'] = time.time() + int(result.get('expires_in', 86400))
        self.write()

    def disk(self, method='GET', endpoint='', **params):
        if not self.config.get('access_token'):
            raise CloudError('Сначала подключите Яндекс Диск')
        if time.time() > self.config.get('expires', 0) - 60:
            token = self.oauth('token', {'grant_type': 'refresh_token', 'refresh_token': self.config.get('refresh_token', ''),
                'client_id': self.config['client_id'], 'client_secret': self.config['client_secret']})
            if token.get('error'):
                raise CloudError('Нужно повторно подключить Яндекс Диск')
            self.set_token(token)
        return self.transport('https://cloud-api.yandex.net/v1/disk/resources' + endpoint + '?' + urlencode(params),
            method, headers={'Authorization': 'OAuth ' + self.config['access_token']})

    def auto_key(self, key_id):
        if not isinstance(key_id, bytes) or len(key_id) != 16:
            raise CloudError('Неверный идентификатор ключа')
        name = ROOT + '/key-' + key_id.hex() + '.json'
        link = self.disk(endpoint='/download', path=name)
        raw = self.transport(link['href'], binary=True,
            headers={'Authorization': 'OAuth ' + self.config['access_token']})
        try:
            obj = json.loads(raw)
            key = base64.b64decode(obj['key'], validate=True)
            if obj['version'] != 1 or obj['id'] != key_id.hex() or len(key) != 32:
                raise ValueError('key')
            return key
        except (ValueError, KeyError, TypeError):
            raise CloudError('Ключ копии на Диске повреждён') from None

    def enable_auto(self):
        self.versions()  # Check account and create folder before writing anything.
        key_id, key = secrets.token_bytes(16), secrets.token_bytes(32)
        name = ROOT + '/key-' + key_id.hex() + '.json'
        raw = json_bytes({'version': 1, 'id': key_id.hex(), 'key': base64.b64encode(key).decode()})
        link = self.disk(endpoint='/upload', path=name, overwrite='false')
        self.transport(link['href'], 'PUT', raw, {'Content-Type': 'application/json'}, binary=True)
        # Never replace a previous server's key. Verify the uploaded key before enabling.
        if not secrets.compare_digest(self.auto_key(key_id), key):
            raise CloudError('Не удалось подтвердить ключ на Яндекс Диске')
        self.config.setdefault('instance', secrets.token_hex(16))
        self.config.update(key=base64.b64encode(key).decode(), salt=base64.b64encode(key_id).decode(),
                           key_mode='yandex', enabled=True)
        self.write()
        self.digest = ''

    def versions(self):
        try:
            self.disk('PUT', path=ROOT)
        except CloudError as error:
            if str(error) != 'Яндекс Диск: HTTP 409':
                raise
        entries, offset = [], 0
        while True:
            result = self.disk(path=ROOT, limit=100, offset=offset, sort='-name')
            batch = result.get('_embedded', {}).get('items', [])
            entries.extend({'name': r['name'], 'size': r.get('size', 0), 'modified': r.get('modified', '')}
                           for r in batch if re.fullmatch(r'hc-\d{20}-[a-f0-9]{32}\.hcb', r.get('name', '')))
            offset += len(batch)
            if len(batch) < 100:
                break
            if offset >= 10000:
                raise CloudError('Слишком много файлов копий')
        return {'items': sorted(entries, key=lambda r: r['name'], reverse=True)}

    def save(self, force=False):
        if not force and time.time() - self.config.get("last_save", 0) < 300:
            return
        if not self.config.get('enabled'):
            raise CloudError('Сначала выберите восстановление или начало нового сохранения')
        document = snapshot(self.factory, self.owner, self.devices)
        fingerprint = hashlib.sha256(json_bytes({k: v for k, v in document.items() if k != 'created_at'})).hexdigest()
        if not force and fingerprint == self.digest:
            return
        data = encrypt(document, base64.b64decode(self.config['key']), base64.b64decode(self.config['salt']),
                       AUTO_MAGIC if self.config.get('key_mode') == 'yandex' else MAGIC)
        name = 'hc-%020d-%s.hcb' % (time.time_ns(), self.config['instance'])
        link = self.disk(endpoint='/upload', path=ROOT + '/' + name, overwrite='false')
        self.transport(link['href'], 'PUT', data, {'Content-Type': 'application/octet-stream'}, binary=True)
        meta = self.disk(path=ROOT + '/' + name)
        if meta.get('size') != len(data) or meta.get('md5') != hashlib.md5(data).hexdigest():
            raise CloudError('Не удалось подтвердить целостность загруженной копии')
        self.config['last_save'] = int(time.time())
        self.digest = fingerprint
        self.last_error = ''
        self.write()
        # Retention affects only THIS server, never the other house's copies.
        own = [r for r in self.versions()['items'] if r['name'].endswith(self.config['instance'] + '.hcb')]
        for row in own[20:]:
            self.disk('DELETE', path=ROOT + '/' + row['name'], permanently='false')

    def preview(self, name, password=None):
        if not re.fullmatch(r'hc-\d{20}-[a-f0-9]{32}\.hcb', str(name)):
            raise CloudError('Неверное имя копии')
        link = self.disk(endpoint='/download', path=ROOT + '/' + name)
        raw = self.transport(link['href'], binary=True,
            headers={'Authorization': 'OAuth ' + self.config['access_token']})
        if raw[:8] == MAGIC and password is None:
            self.staged = None
            return {'password_required': True}
        auto_key = self.auto_key(raw[8:24]) if raw[:8] == AUTO_MAGIC else None
        document, key, salt = decrypt(raw, password, auto_key=auto_key)
        valid_devices(document.get('devices', {}))
        token = secrets.token_urlsafe(32)
        self.staged = (token, time.time() + 300, document, key, salt,
                       'yandex' if raw[:8] == AUTO_MAGIC else 'password')
        profile_table = document['tables'].get('home_profiles', {})
        return {'ticket': token, 'created_at': document['created_at'],
                'profiles': len(profile_table.get('rows', [])),
                'ratings': len(document['tables'].get('user_ratings', {}).get('rows', []))}

    def apply(self, ticket):
        if not self.staged or not secrets.compare_digest(str(ticket), self.staged[0]) or time.time() > self.staged[1]:
            raise CloudError('Подтверждение истекло; выберите копию снова')
        _, _, document, key, salt, key_mode = self.staged
        from connections import IMPORT_LOCK
        if not IMPORT_LOCK.acquire(blocking=False):
            raise CloudError('Дождитесь завершения импорта Кинопоиска и повторите восстановление')
        try:
            restore(self.factory, document, self.owner, self.root / 'before-restore')
        finally:
            IMPORT_LOCK.release()
        self.devices = document.get('devices', {})
        private_write(self.root / 'devices.json', json_bytes(self.devices))
        self.config.update(key=base64.b64encode(key).decode(), salt=base64.b64encode(salt).decode(),
                           key_mode=key_mode, enabled=True)
        self.staged = None
        self.write()
        from connections import REFRESH_EVENT
        REFRESH_EVENT.set()
        return {'ok': True, 'reload': True}

    def run_job(self, action):
        with self.lock:
            if self.job:
                raise CloudError('Дождитесь завершения операции с облаком')
            self.job = True
        def run():
            try:
                with self.lock:
                    action()
            except Exception as error:
                self.last_error = str(error) if isinstance(error, CloudError) else 'Облачная операция не завершена; данные на месте'
            finally:
                self.job = False
        threading.Thread(target=run, daemon=True).start()
        return {'ok': True, 'queued': True}

    def worker(self):
        while True:
            time.sleep(60)
            if self.config.get('enabled') and not self.job:
                try:
                    self.run_job(lambda: self.save())
                except CloudError:
                    pass  # A manual save won the race; keep the worker alive.


_MANAGER = None
_MANAGER_LOCK = threading.Lock()


def manager(factory, owner, root):
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = Manager(root, factory, owner)
            threading.Thread(target=_MANAGER.worker, daemon=True).start()
        return _MANAGER


def allowed_origin(handler):
    origin = handler.headers.get('Origin')
    if not origin:
        return True  # CLI/local server calls. Browser mutation requires JSON below.
    parsed = urlparse(origin)
    hosts = {urlparse('http://' + handler.headers.get('Host', '')).hostname}
    hosts.update(urlparse(os.environ.get(k, '')).hostname for k in ('PUBLIC_LAMPAC_URL', 'PUBLIC_RECOMMENDER_URL', 'LAMPAC_URL'))
    return parsed.scheme in ('http', 'https') and parsed.hostname in hosts and parsed.hostname is not None


def handle(handler, factory, owner, root):
    path = urlparse(handler.path).path
    if not path.startswith('/cloud/'):
        return False
    if not allowed_origin(handler):
        handler.review_response(403, {'error': 'Откройте облако из домашнего HomeCinema'})
        return True
    try:
        m = manager(factory, owner, root)
        if handler.command == 'GET':
            if path == '/cloud/status.json':
                result = m.status()
            elif path == '/cloud/versions.json':
                with m.lock:
                    result = m.versions()
            elif path == '/cloud/qr.svg':
                import qrcode
                from qrcode.image.svg import SvgPathImage
                raw = io.BytesIO()
                qrcode.make('https://oauth.yandex.ru/device', image_factory=SvgPathImage).save(raw)
                body = raw.getvalue()
                handler.send_response(200)
                handler.send_header('Content-Type', 'image/svg+xml')
                handler.send_header('Cache-Control', 'no-store')
                handler.send_header('Content-Length', str(len(body)))
                handler.end_headers()
                handler.wfile.write(body)
                return True
            else:
                raise CloudError('Неизвестный запрос')
        else:
            if handler.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise CloudError('Ожидается JSON')
            length = int(handler.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768:
                raise CloudError('Недопустимый размер запроса')
            payload = json.loads(handler.rfile.read(length))
            if not isinstance(payload, dict):
                raise CloudError('Ожидается объект')
            if m.job:
                raise CloudError('Дождитесь завершения операции с облаком')
            with m.lock:
                if path == '/cloud/connect.json':
                    result = m.start(payload)
                elif path == '/cloud/poll.json':
                    result = m.poll()
                elif path == '/cloud/enable.json':
                    if payload.get('confirm') != 'new':
                        raise CloudError('Подтвердите начало нового сохранения')
                    # The account itself unlocks new copies; no second password.
                    # Legacy clients must update rather than silently changing protection.
                    if payload.get('mode') != 'yandex':
                        raise CloudError('Обновите страницу: новые копии подключаются без отдельного пароля')
                    m.enable_auto()
                    result = m.run_job(lambda: m.save(True))
                elif path == '/cloud/save.json':
                    result = m.run_job(lambda: m.save(True))
                elif path == '/cloud/preview.json':
                    result = m.preview(payload.get('name'), payload.get('password'))
                elif path == '/cloud/restore.json':
                    result = m.apply(payload.get('ticket'))
                elif path == '/cloud/disconnect.json':
                    m.config = {}; m.pending = None; m.staged = None; m.write()
                    result = {'ok': True}
                elif path == '/cloud/device.json':
                    device = payload.get('device')
                    values = payload.get('values')
                    if not re.fullmatch('[A-Za-z0-9_-]{1,80}', str(device)) or not isinstance(values, dict) or set(values) - DEVICE_FIELDS:
                        raise CloudError('Неверные настройки устройства')
                    if len(m.devices) >= 100 and device not in m.devices:
                        raise CloudError('Слишком много устройств')
                    entry = {device: {'values': values, 'updated_at': int(time.time())}}
                    valid_devices(entry)
                    m.devices.update(entry)
                    private_write(m.root / 'devices.json', json_bytes(m.devices))
                    result = {'ok': True}
                elif path == '/cloud/device-restore.json':
                    device = payload.get('device')
                    rows = m.devices
                    selected = rows.get(device) or max(rows.values(), key=lambda r: r['updated_at'], default={})
                    result = {'values': selected.get('values', {})}
                else:
                    raise CloudError('Неизвестный запрос')
        handler.review_response(200, result)
    except (ValueError, TypeError, KeyError) as error:
        handler.review_response(400, {'error': str(error) if isinstance(error, CloudError) else 'Неверный запрос облака'})
    except Exception:
        handler.review_response(503, {'error': 'Облако временно недоступно; локальные данные сохранены'})
    return True

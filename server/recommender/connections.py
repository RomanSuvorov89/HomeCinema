"""Public Kinopoisk profile IDs, separate from stable HomeCinema profile IDs."""
import re
import threading
import time
from urllib.parse import urlparse

IMPORT_LOCK = threading.RLock()
RUNNING = set()
GUARD = threading.Lock()


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS home_connections(
        profile_id TEXT PRIMARY KEY REFERENCES profiles(profile_id) ON DELETE CASCADE,
        kp_id TEXT NOT NULL, checked_at INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '')''')
    c.commit()


def kp_id(value):
    value = str(value or '').strip()
    if value.startswith('https://'):
        url = urlparse(value)
        if url.hostname not in ('kinopoisk.ru', 'www.kinopoisk.ru'):
            raise ValueError('Введите ID или ссылку на профиль Кинопоиска')
        match = re.fullmatch(r'/user/([1-9][0-9]{0,11})/?', url.path)
        value = match[1] if match else ''
    if not re.fullmatch('[1-9][0-9]{0,11}', value):
        raise ValueError('Введите числовой ID или ссылку вида kinopoisk.ru/user/123/')
    return value


def read(c, profile, owner):
    ensure(c)
    row = c.execute('SELECT kp_id,checked_at,error FROM home_connections WHERE profile_id=?', (profile,)).fetchone()
    return {'kp_id': row[0] if row else owner if profile == owner else '',
            'checked_at': row[1] if row else 0, 'error': row[2] if row else ''}


def start_import(factory, profile, callback):
    with GUARD:
        if profile in RUNNING:
            return
        RUNNING.add(profile)
    def run():
        error = ''
        try:
            with IMPORT_LOCK:
                callback(profile)
        except Exception:
            error = 'Импорт не завершён. Проверьте публичность профиля и повторите позже.'
        try:
            c = factory()
            with c:
                c.execute('UPDATE home_connections SET checked_at=?,error=? WHERE profile_id=?',
                          (int(time.time()), error, profile))
            c.close()
        finally:
            with GUARD:
                RUNNING.discard(profile)
    threading.Thread(target=run, daemon=True).start()

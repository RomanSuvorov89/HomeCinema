"""Profile-scoped, per-series semantic track preferences (no episode track IDs)."""
import json
import re
import time


def ensure(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS track_preferences (
        profile_id TEXT NOT NULL, series_key TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('audio','sub')),
        descriptor TEXT NOT NULL, updated_at INTEGER NOT NULL,
        PRIMARY KEY(profile_id,series_key,kind))''')
    connection.commit()


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r'(kp|tmdb|cub):tv:[0-9]{1,12}', value):
        raise ValueError('Invalid series key')
    return value


def read(connection, profile, series):
    ensure(connection)
    rows = connection.execute('SELECT kind,descriptor FROM track_preferences WHERE profile_id=? AND series_key=?',
                              (profile, key(series)))
    return {'series_key': series, 'preferences': {r[0]: json.loads(r[1]) for r in rows}}


def save(connection, profile, payload):
    series = key(payload.get('series_key'))
    kind = payload.get('kind')
    if kind not in ('audio', 'sub'):
        raise ValueError('Invalid track kind')
    descriptor = payload.get('descriptor')
    if not isinstance(descriptor, dict):
        raise ValueError('Invalid descriptor')
    clean = {}
    for field in ('lang', 'title'):
        value = descriptor.get(field, '')
        if not isinstance(value, str) or len(value) > 250:
            raise ValueError('Invalid track text')
        clean[field] = value
    for field in ('forced', 'full', 'off'):
        value = descriptor.get(field, False)
        if type(value) is not bool:
            raise ValueError('Invalid track flag')
        clean[field] = value
    if clean['off'] and kind != 'sub':
        raise ValueError('Only subtitles can be off')
    ensure(connection)
    with connection:
        connection.execute('''INSERT INTO track_preferences VALUES(?,?,?,?,?)
            ON CONFLICT(profile_id,series_key,kind) DO UPDATE SET
            descriptor=excluded.descriptor,updated_at=excluded.updated_at''',
            (profile, series, kind, json.dumps(clean, ensure_ascii=False), int(time.time())))
    return {'ok': True}

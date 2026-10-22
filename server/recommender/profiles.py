"""HomeCinema profiles, personal settings and recoverable client snapshots."""
import copy
from datetime import date, timedelta
import json
import re
import time
import uuid
from urllib.parse import urlparse

SETTINGS = {
    'homecinema_appearance', 'language', 'tmdb_lang', 'source', 'poster_size', 'menu_sort',
    'full_btn_priority', 'interface_sound_level', 'video_quality_default', 'subtitles_start',
    'player_normalization', 'player_subs_shift_time', 'roman_review_filters_v1',
    'roman_hidden_home_v1', 'homecinema_notice_read', 'search_history',
}
HISTORY = {'favorite', 'file_view', 'online_watched_last', 'online_view',
           'online_last_balanser', 'torrents_view', 'torrents_filter_data', 'kp_rating', 'timetable'}
FIELDS = SETTINGS | HISTORY
MISSING = object()


class Conflict(ValueError):
    pass


def ensure(c, owner, label):
    # Existing profiles and ratings keep their original primary keys.
    c.executescript('''CREATE TABLE IF NOT EXISTS home_profiles(
        profile_id TEXT PRIMARY KEY REFERENCES profiles(profile_id), created_at INTEGER NOT NULL, display_name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS home_profile_state(
        profile_id TEXT PRIMARY KEY REFERENCES profiles(profile_id),
        revision INTEGER NOT NULL, document TEXT NOT NULL, updated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS home_profile_backups(
        id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, device_id TEXT NOT NULL,
        document TEXT NOT NULL, created_at INTEGER NOT NULL,
        UNIQUE(profile_id,device_id));''')
    now = int(time.time())
    with c:
        c.execute('INSERT OR IGNORE INTO profiles(profile_id,display_name,source_url,created_at,updated_at) VALUES(?,?,?,?,?)',
                  (owner, label or 'Основной', '', now, now))
        current_label = c.execute('SELECT display_name FROM profiles WHERE profile_id=?', (owner,)).fetchone()[0]
        c.execute('INSERT OR IGNORE INTO home_profiles VALUES(?,?,?)', (owner, now, current_label or 'Основной'))


def generation(c):
    try:
        row = c.execute("SELECT epoch FROM home_restore_meta LIMIT 1").fetchone()
        return row[0] if row else ""
    except Exception:
        return ""


def listing(c, owner):
    rows = c.execute('''SELECT p.profile_id,h.display_name FROM profiles p
        JOIN home_profiles h USING(profile_id) ORDER BY h.created_at,p.profile_id''').fetchall()
    return {'owner_id': owner, 'generation': generation(c), 'profiles': [
        {'id': r[0], 'name': r[1], 'owner': r[0] == owner,
         'lampac_profile_id': '' if r[0] == owner else r[0]} for r in rows]}


def valid_name(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or re.search(r'[<>&\x00-\x1f]', name):
        raise ValueError('Введите имя профиля: от 1 до 40 символов')
    return name.strip()


def create(c, payload):
    name = valid_name(payload.get('name'))
    if c.execute('SELECT COUNT(*) FROM home_profiles').fetchone()[0] >= 12:
        raise ValueError('Достигнут предел: 12 профилей')
    profile = 'hc_' + uuid.uuid4().hex[:20]
    now = int(time.time())
    with c:
        c.execute('INSERT INTO profiles(profile_id,display_name,source_url,created_at,updated_at) VALUES(?,?,?,?,?)', (profile, name.strip(), '', now, now))
        c.execute('INSERT INTO home_profiles VALUES(?,?,?)', (profile, now, name))
    return {'ok': True, 'id': profile}


def state(c, profile):
    row = c.execute('SELECT revision,document FROM home_profile_state WHERE profile_id=?', (profile,)).fetchone()
    return {'profile_id': profile, 'generation': generation(c), 'revision': row[0] if row else 0,
            'values': json.loads(row[1]) if row else {}}


def safe_values(values):
    if not isinstance(values, dict) or set(values) - FIELDS:
        raise ValueError('Недопустимые поля профиля')
    if len(json.dumps(values).encode()) > 2 * 1024 * 1024:
        raise ValueError('Снимок профиля превышает 2 МБ')
    return copy.deepcopy(values)


def union(a, b):
    result = list(a)
    for item in b:
        if item not in result:
            result.append(item)
    return result


def seed_history(remote, local, key=''):
    if isinstance(remote, dict) and isinstance(local, dict):
        # Timeline records have their own clock; progress must not go backwards on an old TV.
        for clock in ('updated', '_hc_updated'):
            if clock in remote and clock in local:
                return local if local[clock] > remote[clock] else remote
        if 'season' in remote and 'season' in local:
            def progress(v):
                return int(v.get('season') or 0), int(v.get('episode') or 0)
            if progress(local) > progress(remote):
                chosen = dict(local)
                if '_hc_updated' in remote and '_hc_updated' not in chosen:
                    chosen['_hc_updated'] = remote['_hc_updated']
                return chosen
            return remote
        result = copy.deepcopy(remote)
        for name, value in local.items():
            result[name] = seed_history(result[name], value, name) if name in result else value
        return result
    if isinstance(remote, list) and isinstance(local, list):
        if key == 'card':
            ids = {str(v.get('id')) for v in remote if isinstance(v, dict)}
            return remote + [v for v in local if isinstance(v, dict) and str(v.get('id')) not in ids]
        return union(remote, local)
    return remote


def three_way(base, local, remote, history=False, key=''):
    if history and key in ('file_view','online_watched_last') and isinstance(remote,dict) and not isinstance(local,dict):
        return remote
    if history and isinstance(local, dict) and isinstance(remote, dict):
        if '_hc_updated' in remote and '_hc_updated' not in local and 'season' in local and 'season' in remote:
            return seed_history(remote, local)
        for clock in ('updated', '_hc_updated'):
            if clock in local and clock in remote:
                return local if local[clock] > remote[clock] else remote
    if local == base or local == remote:
        return remote
    if history and all(isinstance(v, dict) for v in (base, local, remote)):
        if 'updated' in local and 'updated' in remote:
            return local if local['updated'] > remote['updated'] else remote
        result = {}
        for name in base.keys() | local.keys() | remote.keys():
            if key in ('file_view','online_watched_last') and name not in local and name in remote:
                result[name] = remote[name]
                continue
            value = three_way(base.get(name, MISSING), local.get(name, MISSING),
                              remote.get(name, MISSING), True, name)
            if value is not MISSING:
                result[name] = value
        return result
    if history and all(isinstance(v, list) for v in (base, local, remote)):
        # Apply membership changes, not a stale replacement of the entire list.
        if key == 'card':
            def by_id(values):
                return {str(v['id']): v for v in values if isinstance(v, dict) and 'id' in v}
            merged = three_way(by_id(base), by_id(local), by_id(remote), True)
            order = [str(v['id']) for v in remote + local if isinstance(v, dict) and 'id' in v]
            return [merged[k] for k in dict.fromkeys(order) if k in merged]
        removed = [v for v in base if v not in local]
        added = [v for v in local if v not in base]
        return union([v for v in remote if v not in removed], added)
    if remote == base:
        return local
    raise Conflict('Данные изменены на другом устройстве. Обновите профиль и повторите действие.')


def save_state(c, profile, payload):
    base = safe_values(payload.get('base', {}))
    values = safe_values(payload.get('values', {}))
    seed = payload.get('seed') is True
    device = payload.get('device_id')
    if not isinstance(device, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', device):
        raise ValueError('Недопустимый ID устройства')
    # Serialize compare/merge/write across HTTP request threads.
    c.execute('BEGIN IMMEDIATE')
    try:
        if generation(c) != payload.get('generation', ''):
            raise Conflict('На сервере восстановлена облачная копия. Обновите страницу перед сохранением.')
        current = state(c, profile)
        merged = copy.deepcopy(current['values'])
        c.execute('INSERT OR IGNORE INTO home_profile_backups(profile_id,device_id,document,created_at) VALUES(?,?,?,?)',
                  (profile, device, json.dumps(values, ensure_ascii=False), int(time.time())))
        for key, value in values.items():
            if seed:
                merged[key] = seed_history(merged[key], value, key) if key in merged and key in HISTORY else merged.get(key, value)
            else:
                merged[key] = three_way(base.get(key, MISSING), value, merged.get(key, MISSING),
                                        key in HISTORY or key == 'homecinema_notice_read', key)
        revision = current['revision'] + 1
        c.execute('INSERT OR REPLACE INTO home_profile_state VALUES(?,?,?,?)',
                  (profile, revision, json.dumps(merged, ensure_ascii=False), int(time.time())))
        c.commit()
        return {'profile_id': profile, 'revision': revision, 'values': merged, 'generation': generation(c), 'ok': True}
    except Exception:
        c.rollback()
        raise


def catalog_data(c, profile):
    result = {'profile_id': profile, 'updated_at': int(time.time())}
    for table, key, extra in [('user_ratings','ratings',',u.rating'), ('watchlist','watchlist','')]:
        rows = c.execute('SELECT m.*,m.release_year AS year' + extra + ' FROM media m JOIN ' + table
                         + ' u USING(kp_id) WHERE u.profile_id=?', (profile,)).fetchall()
        result[key] = [dict(r) for r in rows]
        result[key + '_count'] = len(rows)
    return result


def notices(c, profile, cache=None):
    today = date.today()
    lower = (today - timedelta(days=30)).isoformat()
    rows = c.execute('''SELECT m.kp_id,m.title,e.episodes_json FROM media m
        JOIN episode_schedules e USING(kp_id) JOIN user_ratings u USING(kp_id)
        WHERE u.profile_id=? AND NOT EXISTS(SELECT 1 FROM recommendation_feedback f
        WHERE f.profile_id=? AND f.kp_id=m.kp_id AND f.status='not_interested') AND NOT EXISTS(SELECT 1 FROM series_tracking st
        WHERE st.profile_id=? AND st.kp_id=m.kp_id AND st.tracking_mode='muted')''', (profile, profile, profile)).fetchall()
    result = []
    for kp, title, data in rows:
        try:
            episodes = [e for e in json.loads(data or '[]') if lower <= e.get('date', '') <= today.isoformat()]
            if not episodes:
                continue
            episode = max(episodes, key=lambda e: (e['date'], e['season'], e['episode']))
            mapped = cache.mapped({'kp_id': kp, 'media_type': 'tv'})[1] if cache else None
            result.append({'id': '%s:%s:%s:%s' % (kp, episode['season'], episode['episode'], episode['date']),
                'kp_id': kp, 'title': title, 'season': episode['season'], 'episode': episode['episode'],
                'date': episode['date'], 'card': mapped, 'text': 'Новая серия по расписанию.'})
        except (TypeError, ValueError, KeyError):
            continue
    return {'items': sorted(result, key=lambda e: e['date'], reverse=True)[:50]}


def handle(handler, connection_factory, owner, label):
    parsed = urlparse(handler.path)
    if parsed.path not in ('/profiles.json', '/profile-state.json'):
        return False
    c = connection_factory()
    try:
        ensure(c, owner, label)
        if handler.command == 'GET':
            if parsed.path == '/profiles.json':
                handler.review_response(200, listing(c, owner))
            else:
                from urllib.parse import parse_qs
                profile = parse_qs(parsed.query).get('id', [''])[0]
                if not c.execute('SELECT 1 FROM home_profiles WHERE profile_id=?', (profile,)).fetchone():
                    raise ValueError('Неизвестный профиль')
                handler.review_response(200, state(c, profile))
        else:
            length = int(handler.headers.get('Content-Length', '0'))
            if not 0 < length <= 4 * 1024 * 1024:
                raise ValueError('Недопустимый размер запроса')
            payload = json.loads(handler.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Ожидается объект')
            if parsed.path == '/profiles.json':
                if payload.get('action') == 'rename':
                    profile = payload.get('profile_id')
                    if not isinstance(profile,str) or not c.execute('SELECT 1 FROM home_profiles WHERE profile_id=?',(profile,)).fetchone():
                        raise ValueError('Неизвестный профиль')
                    name = valid_name(payload.get('name'))
                    with c:
                        c.execute('UPDATE home_profiles SET display_name=? WHERE profile_id=?',(name,profile))
                    handler.review_response(200, {'ok':True})
                else:
                    handler.review_response(200, create(c, payload))
            else:
                profile = payload.get('profile_id')
                if not isinstance(profile, str) or not c.execute('SELECT 1 FROM home_profiles WHERE profile_id=?', (profile,)).fetchone():
                    raise ValueError('Неизвестный профиль')
                handler.review_response(200, save_state(c, profile, payload))
    except Conflict as error:
        handler.review_response(409, {'error': str(error)})
    except (ValueError, TypeError) as error:
        handler.review_response(400, {'error': str(error)})
    except Exception as error:
        print('profiles:', type(error).__name__, str(error), flush=True)
        handler.review_response(503, {'error': 'Профили временно недоступны'})
    finally:
        c.close()
    return True

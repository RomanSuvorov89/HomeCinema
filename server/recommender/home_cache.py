"""Persistent home read model. Only the background worker contacts catalog services."""
import math
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

def config():
    path = Path(os.environ.get('HOME_CACHE_CONFIG', '/data/home-cache-config.json'))
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {}
    except FileNotFoundError:
        return {}


def kinopoisk_enabled():
    env = os.environ.get('KINOPOISK_ENABLED')
    return env.lower() not in ('0','false','no') if env is not None else config().get('kinopoisk_enabled',True)


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS cards (
 card_key TEXT PRIMARY KEY, source TEXT NOT NULL, media_type TEXT NOT NULL,
 catalog_id TEXT NOT NULL, payload_json TEXT NOT NULL, refreshed_at INTEGER NOT NULL,
 UNIQUE(source,media_type,catalog_id));
CREATE TABLE IF NOT EXISTS identity_links (
 kp_id INTEGER NOT NULL, media_type TEXT NOT NULL, card_key TEXT REFERENCES cards(card_key),
 checked_at INTEGER NOT NULL, PRIMARY KEY(kp_id,media_type));
CREATE TABLE IF NOT EXISTS shelves (
 profile_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
 refreshed_at INTEGER NOT NULL, PRIMARY KEY(profile_id,kind));
CREATE TABLE IF NOT EXISTS shelf_items (
 profile_id TEXT NOT NULL, kind TEXT NOT NULL, position INTEGER NOT NULL,
 card_key TEXT NOT NULL REFERENCES cards(card_key), extra_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(profile_id,kind,position),
 FOREIGN KEY(profile_id,kind) REFERENCES shelves(profile_id,kind));
CREATE TABLE IF NOT EXISTS review_snapshots (
 profile_id TEXT PRIMARY KEY, revision TEXT NOT NULL, payload_json TEXT NOT NULL, refreshed_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS worker_status (
 name TEXT PRIMARY KEY, checked_at INTEGER NOT NULL, error TEXT NOT NULL);
"""
KINDS = {'continue': 'Продолжить просмотр', 'ai': 'Рекомендация AI', 'fire': 'Огонь!', 'now': 'Сейчас смотрят',
         'archive': 'Из прошлых лет — для тебя', 'watch': 'Буду смотреть'}

class Cache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript(SCHEMA)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    @staticmethod
    def key(card):
        return '%s:%s:%s' % (card.get('source', 'cub'), card.get('media_type', 'movie'), card['id'])

    def put_card(self, c, card):
        card = dict(card)
        card.pop('roman_review', None)  # Profile features belong to membership, never the shared card.
        key = self.key(card)
        old = c.execute('SELECT payload_json FROM cards WHERE card_key=?', (key,)).fetchone()
        if old:
            previous = json.loads(old['payload_json'])
            for name in ('kinopoisk_id','imdb_id'):
                if not card.get(name) and previous.get(name): card[name] = previous[name]
        c.execute('INSERT OR REPLACE INTO cards VALUES(?,?,?,?,?,?)',
                  (key, card.get('source','cub'), card.get('media_type','movie'), str(card['id']),
                   json.dumps(card, ensure_ascii=False), int(time.time())))
        return key

    def publish(self, profile, kind, entries):
        # Called only for a successful source response; failures must not publish [].
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO shelves VALUES(?,?,?,?)',
                      (profile, kind, KINDS[kind], int(time.time())))
            c.execute('DELETE FROM shelf_items WHERE profile_id=? AND kind=?', (profile, kind))
            for i, (card, extra) in enumerate(entries):
                key = self.put_card(c, card)
                c.execute('INSERT INTO shelf_items VALUES(?,?,?,?,?)',
                          (profile, kind, i, key, json.dumps(extra, ensure_ascii=False)))

    def status(self, name, error=''):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO worker_status VALUES(?,?,?)',
                      (name, int(time.time()), str(error)[:300]))

    def snapshot(self, profile):
        rows = []
        with self.connect() as c:
            # A single read transaction gives a consistent shelf/membership snapshot.
            c.execute('BEGIN')
            for shelf in c.execute("""SELECT * FROM shelves s WHERE profile_id=?
                OR (profile_id='*' AND NOT EXISTS(SELECT 1 FROM shelves own
                    WHERE own.profile_id=? AND own.kind=s.kind))""", (profile, profile)):
                cards = []
                for record in c.execute('''SELECT payload_json,extra_json FROM shelf_items i JOIN cards c USING(card_key)
                    WHERE i.profile_id=? AND kind=? ORDER BY position''', (shelf['profile_id'],shelf['kind'])):
                    card = json.loads(record['payload_json'])
                    extra = json.loads(record['extra_json'])
                    if extra: card['roman_review'] = extra
                    cards.append(card)
                rows.append({'kind':shelf['kind'],'title':shelf['title'],'results':cards,
                             'refreshed_at':shelf['refreshed_at']})
            status = [dict(r) for r in c.execute('SELECT * FROM worker_status')]
        return {'profile_id':profile,'rows':rows,'status':status,'version':1}

    def publish_review(self, profile, items):
        prepared=[]
        for item in items:
            item=dict(item)
            _, card=self.mapped(item)
            if card: item['card']=card
            prepared.append(item)
        payload={'profile_id':profile,'items':prepared,'stage':'cached'}
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        revision=hashlib.sha256(raw.encode()).hexdigest()[:20]
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO review_snapshots VALUES(?,?,?,?)',
                      (profile,revision,raw,int(time.time())))

    def review_snapshot(self, profile, revision=''):
        with self.connect() as c:
            row=c.execute('SELECT * FROM review_snapshots WHERE profile_id=?',(profile,)).fetchone()
        if not row: return {'profile_id':profile,'items':[],'revision':'','warming':True}
        if revision==row['revision']: return {'revision':revision,'unchanged':True}
        data=json.loads(row['payload_json'])
        data.update(revision=row['revision'],refreshed_at=row['refreshed_at'])
        return data

    def mapped(self, item):
        with self.connect() as c:
            row = c.execute('''SELECT l.checked_at,c.payload_json FROM identity_links l LEFT JOIN cards c USING(card_key)
                WHERE kp_id=? AND l.media_type=?''', (item['kp_id'],item.get('media_type','movie'))).fetchone()
        if not row: return False, None
        ttl = 30*86400 if row['payload_json'] else 6*3600
        if time.time()-row['checked_at'] > ttl: return False, None
        return True, json.loads(row['payload_json']) if row['payload_json'] else None

    def mapping(self, item, card):
        with self.connect() as c:
            key = self.put_card(c, card) if card else None
            c.execute('INSERT OR REPLACE INTO identity_links VALUES(?,?,?,?)',
                      (item['kp_id'],item.get('media_type','movie'),key,int(time.time())))


def clean_name(s):
    return re.sub('[^a-zа-я0-9]', '', str(s or '').lower().replace('ё','е'))

class Builder:
    def __init__(self, cache, profile, fetch, personal):
        self.cache, self.profile, self.fetch, self.personal = cache, profile, fetch, personal

    def resolve(self, item):
        found, card = self.cache.mapped(item)
        if found: return card
        typ = item.get('media_type','movie')
        year = item.get('release_year') or item.get('year')
        params = {'query':item['title'],'page':1}
        if year: params['first_air_date_year' if typ=='tv' else 'year'] = year
        json_data = self.fetch('search/'+typ+'?'+urlencode(params))
        if not isinstance(json_data.get('results'),list): raise ValueError('Invalid catalog search response')
        candidates = [c for c in json_data['results'] if
            (not year or str(c.get('release_date') or c.get('first_air_date') or '')[:4]==str(year)) and
            any(clean_name(c.get(n))==clean_name(item['title']) for n in ('title','name','original_title','original_name'))]
        card = dict(candidates[0]) if len(candidates)==1 else None
        if card:
            card.update(source='cub',media_type=typ,kinopoisk_id=str(item['kp_id']))
        self.cache.mapping(item,card)
        return card

    def group(self, kind, selected):
        def resolve(item):
            try: return self.resolve(item), item, None
            except Exception as e: return None,item,str(e)
        with ThreadPoolExecutor(max_workers=4) as pool:
            resolved = list(pool.map(resolve, selected[:24]))
        failures = [err for _,_,err in resolved if err]
        if failures:
            # Do not replace a complete old shelf with an incomplete new one.
            self.cache.status(kind, 'Catalog unavailable: '+failures[0])
            return
        self.cache.publish(self.profile,kind,[(card,item) for card,item,_ in resolved if card])
        self.cache.status(kind)

    def refresh(self):
        refreshed_shared=set()
        # Independent shared groups are committed first, without Kinopoisk dependencies.
        for kind, route in [('fire','top/fire/movie?page=1'),('now','?sort=now_playing&page=1')]:
            try:
                json_data = self.fetch(route)
                if not isinstance(json_data.get('results'),list): raise ValueError('Invalid shelf response')
                cards=[]
                for card in json_data['results'][:30]:
                    card=dict(card);card.setdefault('source','cub')
                    card.setdefault('media_type','tv' if card.get('first_air_date') or card.get('name') else 'movie')
                    cards.append((card,{}))
                self.cache.publish('*',kind,cards)
                refreshed_shared.add(kind)
                self.cache.status(kind)
            except Exception as e: self.cache.status(kind,e)
        try:
            personal = self.personal()
            items, watch = personal[:2]
            airing = personal[2] if len(personal)>2 else []
            schedules_pending=personal[3] if len(personal)>3 else False
        except Exception as e:
            self.cache.status('profile',e)
            return
        current = time.localtime().tm_year
        # Apply owner policy to shared feeds without modifying shared card data.
        # Keep native trend order for Fire; predictions mildly personalize Now.
        context = personal[4] if len(personal)>4 else {}
        excluded = set(map(str, context.get('rated',[])+context.get('seen',[])))
        ended=set(map(str,context.get('ended',[])))
        scores = {str(i['kp_id']): i for i in items}
        for kp,extra in context.get('card_predictions',{}).items():
            scores.setdefault(str(kp),extra)
        shared = {r['kind']:r for r in self.cache.snapshot('*')['rows']}
        for kind in ('fire','now'):
            if kind not in shared: continue
            entries=[]
            for index,card in enumerate(shared[kind]['results']):
                kp=str(card.get('kinopoisk_id') or '')
                extra=scores.get(kp,{})
                if kind=='now' and (kp in excluded or kp in ended or extra.get('feedback') in ('seen','not_interested')): continue
                typ=card.get('media_type','movie')
                year=str(card.get('release_date') or '')[:4]
                # Recent-release shelves are not an archive of classic films.
                # TV premiere year cannot identify a show's current season.
                if typ=='movie' and year.isdigit() and int(year)<current-4: continue
                if re.search(r'^(TS|CAM|HDCAM|TELESYNC|TELECINE|TC|SCR|DVDSCR)(?:\b|[-_])',
                             str(card.get('release_quality') or '').upper()): continue
                prediction=extra.get('predicted_rating')
                if kind=='now' and context and (not isinstance(prediction,(int,float)) or not math.isfinite(prediction)):
                    continue
                rank=1-index/max(1,len(shared[kind]['results']))*.25
                if kind=='now' and prediction is not None:
                    rank*=max(.7,min(1.3,1+(float(prediction)-6)*.12))
                entries.append((card,extra,rank,index))
            if kind=='now': entries.sort(key=lambda e:(-e[2],e[3]))
            self.cache.publish(self.profile,kind,[(card,extra) for card,extra,_,_ in entries])
        allowed=[i for i in items if i.get('feedback') not in ('seen','not_interested')]
        allowed.sort(key=lambda i: (-float(i.get('final_score') or 0),i['kp_id']))
        self.group('ai',[i for i in allowed if current-4 <= int(i.get('release_year') or 0) <= current])
        self.group('archive',[i for i in allowed if 0 < int(i.get('release_year') or 0) < current-4])
        self.group('watch',watch)
        self.group('continue',airing)
        # Publish existing mappings immediately. Resolve only missing/expired identities,
        # independently of browser requests, then publish each completed batch.
        self.cache.publish_review(self.profile,items)
        missing=[i for i in allowed if not self.cache.mapped(i)[0]]
        for offset in range(0,min(len(missing),60),12):
            with ThreadPoolExecutor(max_workers=4) as pool:
                def warm(item):
                    try: self.resolve(item)
                    except Exception as error: self.cache.status('review_mapping',error)
                list(pool.map(warm,missing[offset:offset+12]))
            self.cache.publish_review(self.profile,items)
        self.warming=len(missing)>60 or schedules_pending or len(refreshed_shared)<2
        self.cache.status('profile')


def start_worker(cache, profile, lampac_url, personal):
    settings=config()
    base = os.environ.get('HOME_CUB_BASE_URL') or settings.get('cub_base_url') or lampac_url+'/cub/tmdb.cub.best/'
    base=base.rstrip('/')+'/'
    def fetch(route):
        process = subprocess.run(['curl','-fsSL','--compressed','--connect-timeout','3','--max-time','8',base+route],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        data=json.loads(process.stdout)
        if not isinstance(data,dict): raise ValueError('Invalid CUB JSON')
        return data
    def loop():
        builder=Builder(cache,profile,fetch,personal)
        interval=max(60,int(os.environ.get('HOME_REFRESH_SECONDS') or settings.get('refresh_seconds',900)))
        while True:
            started=time.time()
            try: builder.refresh()
            except Exception as e: cache.status('worker',e)
            cache.status('cycle','')
            print('home cache: '+json.dumps({'profile':profile,'elapsed':round(time.time()-started,2),
                  'rows':[(r['kind'],len(r['results'])) for r in cache.snapshot(profile)['rows']]},ensure_ascii=False),flush=True)
            time.sleep(min(interval,60) if getattr(builder,"warming",False) else interval)
    threading.Thread(target=loop,daemon=True,name='home-cache').start()

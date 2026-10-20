"""Kinoafisha-first schedules with Kinopoisk fallback (background only)."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser

MONTHS={name:i+1 for i,name in enumerate('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())}

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,text):
        if not self.skip:self.parts.append(text)

def parse_entries(html):
    parser=TextParser();parser.feed(html)
    text=re.sub(r'\s+',' ',' '.join(parser.parts))
    tokens=list(re.finditer(r'\b(Сезон|Эпизод)\s+(\d+)\b',text,re.I))
    season=None;result={}
    for i,token in enumerate(tokens):
        if token[1].lower()=='сезон':season=int(token[2]);continue
        if season is None:continue
        end=tokens[i+1].start() if i+1<len(tokens) else len(text)
        block=text[token.end():end]
        match=re.search(r'\b(\d{1,2})\s+('+'|'.join(MONTHS)+r')\s+(20\d{2}|19\d{2})\b',block,re.I)
        day=None
        if match:
            try:day=date(int(match[3]),MONTHS[match[2].lower()],int(match[1])).isoformat()
            except ValueError:pass
        episode=int(token[2]);result[(season,episode)]={'season':season,'episode':episode,'date':day}
    return list(result.values())

def parse_episodes(html):
    return sorted((e for e in parse_entries(html) if e['date']),
                  key=lambda e:(e['date'],e['season'],e['episode']))

PARSER_REVISION=3

SCHEMA='''CREATE TABLE IF NOT EXISTS episode_schedules(
 kp_id INTEGER PRIMARY KEY REFERENCES media(kp_id), episodes_json TEXT NOT NULL DEFAULT '[]',
 checked_at INTEGER NOT NULL DEFAULT 0, attempted_at INTEGER NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS episode_schedule_versions(
 kp_id INTEGER PRIMARY KEY REFERENCES media(kp_id), parser_revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS episode_schedule_links(
 kp_id INTEGER PRIMARY KEY REFERENCES media(kp_id), url TEXT NOT NULL, checked_at INTEGER NOT NULL);'''

def refresh(connection, fetch, state, save, profile, priority_ids=(), batch=12):
    connection.executescript(SCHEMA)
    priority=set(map(int,priority_ids))
    placeholders=','.join('?' for _ in priority) or 'NULL'
    rows=connection.execute('''SELECT m.kp_id,m.title,m.original_title,m.release_year,m.imdb_id,
        COALESCE(e.checked_at,0) checked_at,COALESCE(v.parser_revision,0) parser_revision,
        COALESCE(e.error,'') error,COALESCE(e.episodes_json,'[]') cached_episodes,
        COALESCE(l.url,'') kinoafisha_url,
        COALESCE(e.attempted_at,0) attempted_at
        FROM media m JOIN user_ratings ur USING(kp_id)
        LEFT JOIN episode_schedules e USING(kp_id)
        LEFT JOIN episode_schedule_versions v USING(kp_id)
        LEFT JOIN episode_schedule_links l USING(kp_id)
        WHERE ur.profile_id=? AND (m.media_type='tv' OR m.kp_id IN ('''+placeholders+'''))
        ORDER BY COALESCE(e.checked_at,0),ur.rating DESC,m.kp_id''',(profile,*priority)).fetchall()
    def tracked_state(kp_id,episodes):
        row=connection.execute('SELECT tmdb_status FROM series_tracking WHERE profile_id=? AND kp_id=?',
                               (profile,kp_id)).fetchone()
        return state({'episodes':episodes,'status':row[0] if row else None})
    now=int(time.time())
    due=[r for r in rows if (now-r['checked_at']>=6*3600 or r['parser_revision']<PARSER_REVISION or r['error'])
         and (now-r['attempted_at']>=900 or (r['parser_revision']<PARSER_REVISION and r['checked_at']==r['attempted_at']))]
    due.sort(key=lambda r:(r['kp_id'] not in priority,r['checked_at']))
    # Fetch in a bounded pool; all SQLite writes remain on the owning thread.
    def download(row):
        from kinoafisha import load
        warning='';source_url=''
        try:
            episodes,source_url=load(row,row['kinoafisha_url'])
        except Exception as primary_error:
            warning='Kinoafisha: '+str(primary_error)[:140]
            try:
                entries=parse_entries(fetch('https://www.kinopoisk.ru/film/%s/episodes/'%row['kp_id']))
                episodes=[e for e in entries if e['date']]
                if not episodes:raise ValueError('No dated episodes found (empty page or challenge)')
                if any(not e['date'] for e in entries):warning+='; Kinopoisk schedule is partial'
            except Exception as error:return None,warning+'; '+str(error),source_url,error
        # Keep previously confirmed episodes when a source supplies fewer seasons.
        retained={(e['season'],e['episode']):e for e in json.loads(row['cached_episodes'])}
        retained.update({(e['season'],e['episode']):e for e in episodes})
        episodes=sorted(retained.values(),key=lambda e:(e['date'],e['season'],e['episode']))
        return episodes,warning,source_url,None
    with ThreadPoolExecutor(max_workers=2) as pool:
        downloads=list(pool.map(download,due[:batch]))
    for row,(episodes,warning,source_url,error) in zip(due[:batch],downloads):
        kp_id=row['kp_id']
        try:
            if error:raise error
            if not episodes:raise ValueError('No dated episodes found (empty page or challenge)')
            with connection:
                # Actual season/episode rows prove this is TV, even if an old /film/ vote URL mislabeled it.
                connection.execute("UPDATE media SET media_type='tv' WHERE kp_id=?",(kp_id,))
                connection.execute('''INSERT INTO episode_schedules(kp_id,episodes_json,checked_at,attempted_at,error) VALUES(?,?,?,?,?)
                    ON CONFLICT(kp_id) DO UPDATE SET episodes_json=excluded.episodes_json,
                    checked_at=excluded.checked_at,attempted_at=excluded.attempted_at,
                    error=excluded.error ''',
                    (kp_id,json.dumps(episodes),now,now,warning[:250]))
                connection.execute("INSERT OR REPLACE INTO episode_schedule_versions VALUES(?,?)",(kp_id,PARSER_REVISION))
                if source_url:
                    connection.execute('INSERT OR REPLACE INTO episode_schedule_links VALUES(?,?,?)',(kp_id,source_url,now))
                save(connection,profile,kp_id,tracked_state(kp_id,episodes))
            print('episode schedule: kp_id=%s episodes=%s warning=%s'%(kp_id,len(episodes),warning),flush=True)
        except Exception as error:
            with connection:
                connection.execute('''INSERT INTO episode_schedules(kp_id,attempted_at,error) VALUES(?,?,?)
                    ON CONFLICT(kp_id) DO UPDATE SET attempted_at=excluded.attempted_at,error=excluded.error''',
                    (kp_id,now,str(error)[:250]))
                connection.execute("INSERT OR REPLACE INTO episode_schedule_versions VALUES(?,?)",(kp_id,PARSER_REVISION))
            print('episode schedule failed: kp_id=%s error=%s'%(kp_id,str(error)[:100]),flush=True)
    # Re-evaluate cached schedules as dates pass, even without a network update.
    with connection:
        for row in connection.execute('''SELECT e.kp_id,e.episodes_json FROM episode_schedules e
            JOIN user_ratings ur USING(kp_id) WHERE ur.profile_id=? AND e.checked_at>0''',(profile,)):
            save(connection,profile,row['kp_id'],tracked_state(row['kp_id'],json.loads(row['episodes_json'])))
    return len(due)>batch

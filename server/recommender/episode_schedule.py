"""Kinopoisk episode-page parser and persistent schedule refresh (background only)."""
import json
import os
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen
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

PARSER_REVISION=2
API_LOCK=threading.Lock()
API_LAST=0.0


def fetch_json(url):
    global API_LAST
    # Limit all fallback workers together; no Kinopoisk cookies are sent here.
    with API_LOCK:
        delay=.6-(time.monotonic()-API_LAST)
        if delay>0:time.sleep(delay)
        API_LAST=time.monotonic()
    request=Request(url,headers={'User-Agent':'HomeCinema/0.3 episode-schedule'})
    with urlopen(request,timeout=12) as response:
        raw=response.read(4*1024*1024+1)
    if len(raw)>4*1024*1024:raise ValueError('Episode API response too large')
    return json.loads(raw)


def fallback_episodes(media, known, fetch=None):
    fetch=fetch or fetch_json
    imdb=str(media['imdb_id'] or '')
    exact_id=bool(re.fullmatch(r'tt[0-9]+',imdb))
    if exact_id:
        show=fetch('https://api.tvmaze.com/lookup/shows?'+urlencode({'imdb':imdb}))
        if not isinstance(show,dict) or show.get('externals',{}).get('imdb')!=imdb:
            raise ValueError('Episode API IMDb mismatch')
    else:
        title=media['original_title']
        year=media['release_year']
        if not title or not year:raise ValueError('Missing identity for episode fallback')
        result=fetch('https://api.tvmaze.com/search/shows?'+urlencode({'q':title}))
        if not isinstance(result,list):raise ValueError('Invalid episode search response')
        matches={}
        for item in result:
            candidate=item.get('show',{})
            if (candidate.get('name','').strip().casefold()==title.strip().casefold()
                    and str(candidate.get('premiered') or '')[:4]==str(year)):
                matches[candidate.get('id')]=candidate
        if len(matches)!=1:raise ValueError('Episode fallback identity is missing or ambiguous')
        show=next(iter(matches.values()))
    show_id=show.get('id')
    if type(show_id) is not int or show_id<=0:raise ValueError('Invalid episode show ID')
    payload=fetch('https://api.tvmaze.com/shows/%s/episodes'%show_id)
    if not isinstance(payload,list):raise ValueError('Invalid episode list response')
    episodes={}
    for item in payload:
        season,number,day=item.get('season'),item.get('number'),item.get('airdate')
        if type(season) is not int or type(number) is not int or season<1 or number<1:continue
        try:day=date.fromisoformat(day).isoformat()
        except (ValueError,TypeError):continue
        episodes[(season,number)]={'season':season,'episode':number,'date':day}
    if not episodes:raise ValueError('Episode fallback has no dated episodes')
    # Without an external ID, also prove identity with the already known schedule.
    if not exact_id:
        anchors={(e['season'],e['episode']):e['date'] for e in known}
        shared=set(anchors)&set(episodes)
        if len(shared)<2 or any(anchors[key]!=episodes[key]['date'] for key in shared):
            raise ValueError('Episode fallback does not match known episode dates')
    return list(episodes.values())


SCHEMA='''CREATE TABLE IF NOT EXISTS episode_schedules(
 kp_id INTEGER PRIMARY KEY REFERENCES media(kp_id), episodes_json TEXT NOT NULL DEFAULT '[]',
 checked_at INTEGER NOT NULL DEFAULT 0, attempted_at INTEGER NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS episode_schedule_versions(
 kp_id INTEGER PRIMARY KEY REFERENCES media(kp_id), parser_revision INTEGER NOT NULL);'''

def refresh(connection, fetch, state, save, profile, priority_ids=(), batch=12):
    connection.executescript(SCHEMA)
    priority=set(map(int,priority_ids))
    placeholders=','.join('?' for _ in priority) or 'NULL'
    rows=connection.execute('''SELECT m.kp_id,m.original_title,m.release_year,m.imdb_id,
        COALESCE(e.checked_at,0) checked_at,COALESCE(v.parser_revision,0) parser_revision,
        COALESCE(e.error,'') error,COALESCE(e.episodes_json,'[]') cached_episodes,
        COALESCE(e.attempted_at,0) attempted_at
        FROM media m JOIN user_ratings ur USING(kp_id)
        LEFT JOIN episode_schedules e USING(kp_id)
        LEFT JOIN episode_schedule_versions v USING(kp_id)
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
        try:
            entries=parse_entries(fetch('https://www.kinopoisk.ru/film/%s/episodes/'%row['kp_id']))
            episodes=[e for e in entries if e['date']]
            if not episodes:raise ValueError('No dated episodes found (empty page or challenge)')
            cached=json.loads(row['cached_episodes'])
            latest=max(e['season'] for e in episodes)
            missing=[e for e in entries if not e['date'] and e['season']>=latest]
            warning=''
            if missing:
                try:
                    if os.environ.get('EPISODE_FALLBACK_ENABLED','1').lower() in ('0','false','no'):
                        raise ValueError('Episode fallback disabled')
                    extra=fallback_episodes(row,episodes)
                    merged={(e['season'],e['episode']):e for e in cached}
                    merged.update({(e['season'],e['episode']):e for e in extra})
                    # Keep exact dates from Kinopoisk when both sources provide them.
                    merged.update({(e['season'],e['episode']):e for e in episodes})
                    episodes=list(merged.values())
                    if any((e['season'],e['episode']) not in merged for e in missing):
                        warning='Partial schedule: some announced episodes still have no dates'
                except Exception as error:
                    warning='Partial schedule: '+str(error)
            retained={(e['season'],e['episode']):e for e in cached}
            retained.update({(e['season'],e['episode']):e for e in episodes})
            episodes=sorted(retained.values(),key=lambda e:(e['date'],e['season'],e['episode']))
            return episodes,warning,None
        except Exception as error:return None,'',error
    with ThreadPoolExecutor(max_workers=2) as pool:
        downloads=list(pool.map(download,due[:batch]))
    for row,(episodes,warning,error) in zip(due[:batch],downloads):
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

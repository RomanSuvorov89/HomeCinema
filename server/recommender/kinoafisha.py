"""Public Kinoafisha schedules, matched by title and premiere year."""
import re
import subprocess
import threading
import time
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit

BASE='https://www.kinoafisha.info'
MONTHS={name:i+1 for i,name in enumerate('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())}
LOCK=threading.Lock()
LAST_REQUEST=0.0
VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}


def fetch_page(url):
    global LAST_REQUEST
    if urlsplit(url).hostname!='www.kinoafisha.info' or urlsplit(url).scheme!='https':
        raise ValueError('Invalid Kinoafisha URL')
    with LOCK:
        delay=.5-(time.monotonic()-LAST_REQUEST)
        if delay>0:time.sleep(delay)
        LAST_REQUEST=time.monotonic()
    result=subprocess.run(['curl','-fsSL','--compressed','--proto','=https','--proto-redir','=https',
        '--max-redirs','3','--connect-timeout','4','--max-time','12','--max-filesize','4194304',
        '-A','Mozilla/5.0',url],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
    if len(result.stdout)>4194304:raise ValueError('Kinoafisha page is too large')
    return result.stdout.decode('utf-8','replace')


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.captures=[];self.row=None;self.row_depth=0
        self.episodes=[];self.headings=[];self.links=[];self.text=[]
        self.anchor=None;self.anchor_depth=0
        self.feed(html)

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag not in VOID:self.stack.append(tag)
        depth=len(self.stack)
        classes=set(attrs.get('class','').split())
        if 'newSeriesList_item' in classes:
            self.row={};self.row_depth=depth
        if self.row is not None:
            for field,css in [('season','newSeriesList_season'),('episode','newSeriesList_series'),('date','newSeriesList_date')]:
                if css in classes:
                    parts=[];self.row[field]=parts;self.captures.append((depth,parts))
        if tag=='h1':
            parts=[];self.headings.append(parts);self.captures.append((depth,parts))
        if tag=='a':
            self.anchor=[attrs.get('href',''),[]];self.anchor_depth=depth
        if tag=='img' and self.anchor and attrs.get('alt'):
            self.anchor[1].append(attrs['alt'])

    def handle_data(self,text):
        if 'script' in self.stack or 'style' in self.stack:return
        self.text.append(text)
        for _,parts in self.captures:parts.append(text)
        if self.anchor:self.anchor[1].append(text)

    def handle_endtag(self,tag):
        if tag not in self.stack:return
        depth=len(self.stack)-self.stack[::-1].index(tag)
        if self.anchor and self.anchor_depth>=depth:
            self.links.append((self.anchor[0],' '.join(self.anchor[1])))
            self.anchor=None
        if self.row is not None and self.row_depth>=depth:
            try:
                season=int(re.search(r'\d+',' '.join(self.row['season']))[0])
                episode=int(re.search(r'\d+',' '.join(self.row['episode']))[0])
                value=' '.join(self.row['date']).strip().lower()
                found=re.fullmatch(r'(\d{1,2})\s+([а-я]+)\s+(\d{4})',value)
                day=date(int(found[3]),MONTHS[found[2]],int(found[1])).isoformat()
                if season>0 and episode>0:self.episodes.append({'season':season,'episode':episode,'date':day})
            except (KeyError,TypeError,ValueError):pass
            self.row=None
        self.captures=[c for c in self.captures if c[0]<depth]
        del self.stack[depth-1:]


def clean(value):
    return re.sub(r'[\W_]+','',str(value or '').casefold().replace('ё','е'))


def series_url(value):
    parsed=urlsplit(urljoin(BASE,value))
    if parsed.scheme=='https' and parsed.hostname=='www.kinoafisha.info' and re.fullmatch(r'/series/[a-z0-9-]+/',parsed.path):
        if parsed.path.split('/')[2] not in {'calendar','ratings','news','new','best','catalog'}:
            return BASE+parsed.path
    return None


def matches(page,media):
    headings=[' '.join(parts).strip() for parts in page.headings]
    names={clean(media['title']),clean(media['original_title'])}-{''}
    matched=any(clean(re.split(r'\s*\(',h,1)[0]) in names for h in headings)
    text=re.sub(r'\s+',' ',' '.join(page.text))
    year=re.search(r'Год выпуска\s*(\d{4})',text,re.I)
    if not year:
        year=re.search(r'\b((?:19|20)\d{2})\b',' '.join(headings))
    return matched and year is not None and str(media['release_year'])==year[1]


def load(media,cached_url='',fetch=None):
    fetch=fetch or fetch_page
    root=series_url(cached_url) if cached_url else None
    if root:
        page=Page(fetch(root))
        if not matches(page,media):raise ValueError('Cached Kinoafisha identity no longer matches')
    else:
        if not media['release_year']:raise ValueError('Premiere year missing for Kinoafisha matching')
        found={}
        for query in dict.fromkeys(filter(None,(media['original_title'],media['title']))):
            search=Page(fetch(BASE+'/search/?'+urlencode({'q':query})))
            candidates={series_url(href) for href,_ in search.links}-{None}
            if len(candidates)>8:raise ValueError('Too many Kinoafisha candidates')
            for url in sorted(candidates):
                candidate=Page(fetch(url))
                if matches(candidate,media):found[url]=candidate
            if found:break
        if len(found)!=1:raise ValueError('Kinoafisha identity is missing or ambiguous')
        root,page=next(iter(found.items()))
    episodes={(e['season'],e['episode']):e for e in page.episodes}
    # Fetch the two latest announced seasons, including the current one if the next is future.
    seasons={}
    for href,_ in page.links:
        url=urljoin(root,href)
        match=re.fullmatch(re.escape(root)+r'seasons/s([1-9][0-9]*)/',url)
        if match:seasons[int(match[1])]=url
    for season in sorted(seasons,reverse=True)[:2]:
        detail=Page(fetch(seasons[season]))
        rows=[e for e in detail.episodes if e['season']==season]
        episodes.update({(e['season'],e['episode']):e for e in rows})
    if not episodes:raise ValueError('Kinoafisha has no dated episode rows')
    return sorted(episodes.values(),key=lambda e:(e['date'],e['season'],e['episode'])),root

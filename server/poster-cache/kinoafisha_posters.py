"""Resolve series posters using verified title/year identities, never a guessed slug."""
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import sqlite3
import subprocess
import threading
import time
from urllib.parse import urlencode, urljoin, urlsplit

BASE = 'https://www.kinoafisha.info'
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
REQUEST_LOCK = threading.Lock()
LAST_REQUEST = 0.0


def fetch_page(url):
    global LAST_REQUEST
    if urlsplit(url).hostname != 'www.kinoafisha.info' or urlsplit(url).scheme != 'https':
        raise ValueError('Invalid Kinoafisha page')
    with REQUEST_LOCK:
        delay = .5 - (time.monotonic() - LAST_REQUEST)
        if delay > 0:
            time.sleep(delay)
        LAST_REQUEST = time.monotonic()
    result = subprocess.run(['curl','-fsSL','--compressed','--proto','=https','--proto-redir','=https',
        '--max-redirs','3','--connect-timeout','4','--max-time','10','--max-filesize','4194304',
        '-A','Mozilla/5.0',url], check=True, capture_output=True, timeout=12)
    if len(result.stdout) > 4194304:
        raise ValueError('Page too large')
    return result.stdout.decode('utf-8', 'replace')


def image_url(value):
    url = urljoin(BASE, value or '')
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if parsed.scheme == 'https' and (host == 'kinoafisha.info' or host.endswith('.kinoafisha.info')) and not parsed.username:
        if re.search(r'\.(?:jpe?g|png|webp)(?:$|\?)', url, re.I):
            return url
    return None


class Page(HTMLParser):
    def __init__(self, text, url=BASE):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.stack = []
        self.headings = []
        self.text = []
        self.links = []
        self.images = []
        self.meta = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        context = ' '.join(x[1] for x in self.stack) + ' ' + attrs.get('class', '')
        if tag not in VOID:
            self.stack.append((tag, attrs.get('class', '')))
        if tag == 'a':
            self.links.append(urljoin(self.url, attrs.get('href', '')))
        if tag == 'img' and ('poster' in context.lower() or 'постер' in attrs.get('alt', '').lower()):
            for key in ('data-src', 'data-original', 'src'):
                url = image_url(attrs.get(key))
                if url and url not in self.images:
                    self.images.append(url)
        if tag == 'meta' and attrs.get('property', '').lower() == 'og:image':
            url = image_url(attrs.get('content'))
            if url:
                self.meta.append(url)

    def handle_endtag(self, tag):
        tags = [t[0] for t in self.stack]
        if tag in tags:
            del self.stack[len(tags) - 1 - tags[::-1].index(tag):]

    def handle_data(self, value):
        tags = [t[0] for t in self.stack]
        if 'script' in tags or 'style' in tags:
            return
        self.text.append(value)
        if 'h1' in tags:
            self.headings.append(value)

    def poster(self):
        return (self.images + self.meta + [None])[0]


def clean(value):
    return re.sub(r'[\W_]+', '', str(value or '').casefold().replace('ё','е'))


def matches(page, media):
    heading = ' '.join(page.headings).strip()
    names = {clean(media.get('title')), clean(media.get('original_title'))} - {''}
    year = re.search(r'Год выпуска\s*(\d{4})', ' '.join(page.text), re.I)
    if not year:
        year = re.search(r'\b((?:19|20)\d{2})\b', heading)
    return clean(re.split(r'\s*\(', heading, 1)[0]) in names and year and str(media.get('release_year')) == year[1]


class KinoafishaPosters:
    def __init__(self, catalog, fetch=None):
        self.catalog = Path(catalog)
        self.fetch = fetch or fetch_page
        self.roots = {}

    def media(self, kp_id):
        path = self.catalog / 'recommender.sqlite3'
        if not path.is_file():
            return None, ''
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            media = conn.execute('SELECT * FROM media WHERE kp_id=?', (int(kp_id),)).fetchone()
            if not media or media['media_type'] != 'tv':
                return None, ''
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_schedule_links'").fetchone()
            row = conn.execute('SELECT url FROM episode_schedule_links WHERE kp_id=?', (int(kp_id),)).fetchone() if exists else None
            return dict(media), row[0] if row else ''

    def resolve(self, kp_id):
        cached = self.roots.get(kp_id)
        if cached and time.monotonic() - cached[0] < 21600:
            return cached[1:]
        media, root = self.media(kp_id)
        if not media or not media.get('release_year'):
            return '', None
        if root and not re.fullmatch(re.escape(BASE) + r'/series/[a-z0-9-]+/', root):
            root = ''
        if root:
            page = Page(self.fetch(root), root)
            if not matches(page, media):
                raise ValueError('Kinoafisha identity changed')
        else:
            found = {}
            for query in dict.fromkeys(filter(None, (media.get('original_title'), media.get('title')))):
                search = Page(self.fetch(BASE + '/search/?' + urlencode({'q': query})))
                links = {u for u in search.links if re.fullmatch(re.escape(BASE) + r'/series/[a-z0-9-]+/', u)}
                links = {u for u in links if u.split('/')[-2] not in {'calendar','ratings','news','new','best','catalog'}}
                if len(links) > 8:
                    raise ValueError('Ambiguous Kinoafisha search')
                for url in sorted(links):
                    candidate = Page(self.fetch(url), url)
                    if matches(candidate, media):
                        found[url] = candidate
                if found:
                    break
            if len(found) != 1:
                raise ValueError('Kinoafisha title/year missing or ambiguous')
            root, page = next(iter(found.items()))
        self.roots[kp_id] = (time.monotonic(), root, page)
        return root, page

    def sources(self, kp_id, season=0):
        root, page = self.resolve(kp_id)
        if not root:
            return []
        result = []
        if season:
            url = root + 'seasons/s' + str(season) + '/'
            # Only request a season linked by the verified series page.
            if url in page.links:
                try:
                    detail = Page(self.fetch(url), url)
                    image = detail.poster()
                    heading = ' '.join(detail.headings).lower()
                    number = str(int(season))
                    season_heading = re.search(r'(?:сезон\s*' + number + r'(?!\d)|(?<!\d)' + number + r'\s*(?:-?й\s*)?сезон)', heading)
                    if season_heading and image and image != page.poster():
                        result.append(('kinoafisha-season', image))
                except Exception as error:
                    print('season poster fallback:', kp_id, season, str(error)[-160:], flush=True)
        if page.poster():
            result.append(('kinoafisha-main', page.poster()))
        return list(dict.fromkeys(result))

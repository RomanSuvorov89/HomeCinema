"""Public Kinopoisk trivia, cached independently from profiles and recommendations."""
import html
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

LOCKS = [threading.Lock() for _ in range(64)]
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36'


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.skip+=1
        if tag in ('br','p','li'): self.parts.append(' ')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def clean(value):
    parser=Text(); parser.feed(str(value or ''))
    return ' '.join(html.unescape(''.join(parser.parts)).split())[:6000]


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts=[]; self.script=None; self.parts=[]; self.blocks=[]
        self.depth=0; self.capture=None; self.text=[]; self.canonical=''; self.spoiler=False
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='link' and attrs.get('rel')=='canonical': self.canonical=attrs.get('href','')
        if tag=='script' and (attrs.get('id')=='__NEXT_DATA__' or attrs.get('type') in ('application/json','application/ld+json')):
            self.script=True; self.parts=[]
        if tag not in ('br','img','hr','input','meta','link','source','wbr'): self.depth+=1
        classes=attrs.get('class','')
        marker=attrs.get('data-testid','')
        if self.capture is None and (re.search(r'(^|\s)trivia(\s|$)|(?:trivia|fact)[_-](?:text|content)',classes,re.I) or marker in ('trivia','fact','film-fact')):
            self.capture=self.depth; self.text=[]; self.spoiler=False
        if self.capture is not None and ('spoiler' in classes.casefold() or attrs.get('data-spoiler')=='true'):
            self.spoiler=True
    def handle_data(self, data):
        if self.script: self.parts.append(data)
        elif self.capture is not None: self.text.append(data)
    def handle_endtag(self, tag):
        if tag=='script' and self.script:
            try: self.scripts.append(json.loads(''.join(self.parts)))
            except ValueError: pass
            self.script=None
        if self.capture==self.depth:
            self.blocks.append({'text':' '.join(self.text),'spoiler':self.spoiler});self.capture=None
        if tag not in ('br','img','hr','input','meta','link','source','wbr'): self.depth=max(0,self.depth-1)


def parse_facts(page, kp_id):
    parser=Page();parser.feed(page)
    canonical=re.search(r'/(?:film|series)/(\d+)/',parser.canonical)
    if canonical and canonical[1]!=str(kp_id): raise ValueError('Different Kinopoisk card')
    items=[]; seen=set()
    def add(value):
        spoiler=False
        if isinstance(value,dict):
            owner=value.get('filmId') or value.get('movieId')
            if owner and str(owner)!=str(kp_id): return
            spoiler=bool(value.get('spoiler') or value.get('isSpoiler'))
            value=value.get('text') or value.get('value') or value.get('description')
        if not isinstance(value,str): return
        text=clean(value)
        if len(text)<15 or text.casefold() in seen: return
        seen.add(text.casefold());items.append({'text':text,'spoiler':spoiler})
    def collection(value):
        if isinstance(value,list):
            for item in value: collection(item)
        elif isinstance(value,str): add(value)
        elif isinstance(value,dict):
            if any(k in value for k in ('text','value','description')): add(value)
            for key in ('items','nodes','edges','node','data'):
                if key in value: collection(value[key])
    def walk(value):
        if isinstance(value,dict):
            kind=str(value.get('__typename',''))
            if re.fullmatch(r'(?:Film|Movie|Tv|Series)?(?:Fact|Trivia)',kind,re.I): add(value)
            for key,item in value.items():
                if key.casefold() in ('facts','trivia','trivias','didyouknow'): collection(item)
                else: walk(item)
        elif isinstance(value,list):
            for item in value: walk(item)
    for script in parser.scripts: walk(script)
    for block in parser.blocks: add(block)
    return items[:200]


def fetch_page(url):
    result=subprocess.run(['curl','-fsSL','--compressed','--proto','=https','--proto-redir','=https',
        '--max-redirs','3','--connect-timeout','4','--max-time','8','--max-filesize','8388608',
        '-A',UA,url],capture_output=True,timeout=10)
    if result.returncode: raise OSError('Kinopoisk page unavailable')
    return result.stdout.decode('utf-8','replace')


def get_facts(root, kp_id, media_type, fetcher=fetch_page):
    kp_id=str(kp_id)
    if not re.fullmatch(r'[1-9][0-9]{0,9}',kp_id) or media_type not in ('tv','movie'):
        raise ValueError('Invalid Kinopoisk card')
    route='series' if media_type=='tv' else 'film'
    source='https://www.kinopoisk.ru/'+route+'/'+kp_id+'/didyouknow/'
    folder=Path(root);folder.mkdir(parents=True,exist_ok=True)
    path=folder/(kp_id+'.json')
    with LOCKS[int(kp_id)%len(LOCKS)]:
        old={}
        if path.is_file():
            try: old=json.loads(path.read_text())
            except ValueError: pass
        if not isinstance(old,dict): old={}
        if old.get('stale') and old.get('attempted_at',0)+300>time.time(): return old
        ttl=7*86400 if old.get('items') else 300
        if old.get('checked_at',0)+ttl>time.time(): return old
        error=''
        try:
            page=fetcher(source)
            items=parse_facts(page,kp_id)
            if not items and re.search(r'captcha|showcaptcha|SmartCaptcha',page,re.I):
                raise OSError('Kinopoisk requested verification')
            if not items:
                items=parse_facts(fetcher(source.replace('didyouknow/','')),kp_id)
        except Exception:
            items=[];error='Кинопоиск сейчас не отдал факты. Попробуйте позже или откройте источник.'
        if not items and old.get('items'):
            payload=dict(old,stale=True,attempted_at=int(time.time()))
        else:
            payload={'kp_id':kp_id,'source':'Кинопоиск','source_url':source,'items':items,
                 'checked_at':int(time.time()),'error':error}
        fd,temporary=tempfile.mkstemp(prefix='facts-',dir=folder)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(payload,stream,ensure_ascii=False)
            os.replace(temporary,path)
        finally: Path(temporary).unlink(missing_ok=True)
        return payload

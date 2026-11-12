"""Bounded, disk-backed access to public TMDB card metadata using verified DoH."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlencode

RESOURCE = re.compile(r'(?:tv|movie|collection)/[1-9][0-9]{0,9}(?:/(?:credits|recommendations|similar|videos))?')
APPEND = {'content_ratings','release_dates','external_ids','keywords','alternative_titles','images','credits'}


class TmdbMetadata:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.locks = [threading.Lock() for _ in range(64)]
        self.slots = threading.BoundedSemaphore(3)
        self.failures = {}

    def fetch(self, resource, query):
        with self.slots, tempfile.TemporaryDirectory(dir=self.root) as temporary:
            output = Path(temporary) / 'response.json'
            result = subprocess.run([
                'curl','-4','--noproxy','*','--fail','--silent','--show-error',
                '--doh-url',os.environ.get('TMDB_DOH_URL','https://cloudflare-dns.com/dns-query'),
                '--proto','=https','--connect-timeout','4','--max-time','8',
                '--max-filesize','2097152','--output',str(output),
                'https://api.themoviedb.org/3/'+resource+'?'+urlencode(query)
            ], capture_output=True, timeout=10)
            if result.returncode:
                raise OSError('TMDB metadata request failed (curl '+str(result.returncode)+')')
            raw = output.read_bytes()
            if len(raw) > 2097152:
                raise ValueError('Metadata response too large')
            payload = json.loads(raw)
            if not isinstance(payload,dict) or payload.get('success') is False or payload.get('blocked'):
                raise ValueError('Invalid TMDB metadata response')
            if resource.count('/') == 1:
                if str(payload.get('id')) != resource.split('/')[1] or not (payload.get('name') or payload.get('title')):
                    raise ValueError('Wrong TMDB card identity')
            elif resource.endswith('/credits'):
                if not isinstance(payload.get('cast'),list):
                    raise ValueError('Invalid credits response')
            elif not isinstance(payload.get('results'),list):
                raise ValueError('Invalid metadata list')
            return payload

    def get(self, resource, api_key, language='ru-RU', append='', image_language=''):
        if not RESOURCE.fullmatch(resource):
            raise ValueError('Invalid metadata resource')
        if not re.fullmatch(r'[a-fA-F0-9]{32}',api_key or ''):
            raise ValueError('Missing or invalid TMDB API key')
        if not re.fullmatch(r'[A-Za-z0-9,-]{1,64}',language):
            raise ValueError('Invalid language')
        fields = sorted(set(append.split(','))) if append else []
        if not set(fields) <= APPEND:
            raise ValueError('Invalid appended metadata')
        if image_language and not re.fullmatch(r'[A-Za-z0-9,-]{1,64}',image_language):
            raise ValueError('Invalid image language')
        query = {'api_key':api_key,'language':language}
        if fields: query['append_to_response'] = ','.join(fields)
        if image_language: query['include_image_language'] = image_language
        # Credentials never enter filenames, persisted content or log messages.
        identity = [resource,language,fields,image_language]
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        path = self.root / (key+'.json')
        with self.locks[int(key[:8],16) % len(self.locks)]:
            stale = None
            if path.is_file():
                try:
                    stale = json.loads(path.read_bytes())
                    if time.time()-path.stat().st_mtime < 21600:
                        return stale
                except ValueError:
                    stale = None
            if self.failures.get(key,0) > time.monotonic():
                if stale is not None: return stale
                raise OSError('Previous metadata request failed; retry later')
            try:
                payload = self.fetch(resource,query)
                fd,temporary = tempfile.mkstemp(prefix='metadata-save-',dir=self.root)
                try:
                    with os.fdopen(fd,'w',encoding='utf-8') as stream:
                        json.dump(payload,stream,ensure_ascii=False)
                        stream.flush();os.fsync(stream.fileno())
                    os.replace(temporary,path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
                return payload
            except Exception:
                now = time.monotonic()
                if len(self.failures) > 4096:
                    self.failures = {k:v for k,v in self.failures.items() if v > now}
                self.failures[key] = now+60
                if stale is not None: return stale
                raise OSError('TMDB metadata unavailable') from None

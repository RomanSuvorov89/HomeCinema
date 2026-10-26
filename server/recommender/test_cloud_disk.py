import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import cloud_disk as cloud
import connections
import profiles


class Disk:
    def __init__(self):
        self.files = {}
        self.polls = 0
        self.requests = []
        self.broken = False

    def __call__(self, url, method='GET', data=None, headers=None, binary=False):
        from urllib.parse import urlparse, parse_qs
        self.requests.append((url, method, headers))
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path == '/device/code':
            return {'device_code':'SECRET_CODE', 'user_code':'USER123', 'verification_url':'https://oauth.yandex.ru/device', 'expires_in':300, 'interval':5}
        if parsed.path == '/token':
            self.polls += 1
            if self.polls == 1:
                return {'error': 'authorization_pending'}
            return {'access_token':'SECRET_TOKEN', 'refresh_token':'SECRET_REFRESH', 'expires_in':86400}
        if parsed.hostname == 'uploader.yandex.net':
            self.files[parsed.path[1:]] = data
            return b''
        if parsed.hostname == 'downloader.yandex.ru':
            return self.files[parsed.path[1:]]
        name = query.get('path', [''])[0].rsplit('/',1)[-1]
        if parsed.path.endswith('/upload'):
            return {'href': 'https://uploader.yandex.net/' + name}
        if parsed.path.endswith('/download'):
            return {'href': 'https://downloader.yandex.ru/' + name}
        if method == 'PUT':
            return {}
        if method == 'DELETE':
            del self.files[name]
            return {}
        if name == 'HomeCinema':
            offset = int(query.get('offset',[0])[0])
            return {'_embedded': {'items':[{'name':k,'size':len(v),'modified':'2026-10-22'} for k,v in sorted(self.files.items(),reverse=True)][offset:offset+100]}}
        raw = self.files[name]
        return {'size':len(raw), 'md5':'wrong' if self.broken else hashlib.md5(raw).hexdigest()}


class CloudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'source.sqlite3'
        c = self.factory()
        c.executescript((Path(__file__).parent/'schema.sql').read_text())
        profiles.ensure(c, 'owner', 'Роман')
        connections.ensure(c)
        c.execute("INSERT INTO media(kp_id,media_type,title) VALUES(42,'tv','Сериал')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',42,8)")
        c.execute("INSERT INTO home_connections(profile_id,kp_id) VALUES('owner','123456')")
        c.commit()
        profiles.save_state(c, 'owner', {'device_id':'pc','seed':True,'values':{
            'homecinema_appearance':'apple','file_view':{'episode':{'updated':100,'percent':100}}}})
        c.close()
        self.disk = Disk()
        self.m = cloud.Manager(self.root/'cloud', self.factory, 'owner', self.disk)
        self.password = 'Test recovery password 123'

    def tearDown(self):
        self.tmp.cleanup()

    def factory(self):
        c=sqlite3.connect(self.db, timeout=5)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def enable(self):
        salt=b's'*16
        self.m.config.update(access_token='SECRET_TOKEN',expires=10**12,instance='a'*32,
            key=cloud.base64.b64encode(cloud.derive(self.password,salt)).decode(),
            salt=cloud.base64.b64encode(salt).decode(),enabled=True)

    def test_yandex_only_restore_on_independent_server_and_retention(self):
        self.m.config.update(access_token='SECRET_TOKEN', expires=10**12)
        self.m.enable_auto()
        self.m.save(True)
        name = self.m.versions()['items'][0]['name']
        raw = self.disk.files[name]
        self.assertEqual(raw[:8], cloud.AUTO_MAGIC)
        self.assertNotIn(b'homecinema_appearance', raw)
        keys = [k for k in self.disk.files if k.startswith('key-')]
        self.assertEqual(len(keys), 1)
        other = cloud.Manager(self.root/'independent-server', self.factory, 'new_owner', self.disk)
        other.config.update(access_token='OTHER_TOKEN', expires=10**12)
        preview = other.preview(name)
        self.assertEqual(preview['ratings'], 1)
        self.assertNotIn('key', preview)
        other.apply(preview['ticket'])
        self.assertEqual(other.config['key_mode'], 'yandex')
        c = self.factory()
        self.assertEqual(c.execute("SELECT rating FROM user_ratings WHERE profile_id='new_owner'").fetchone()[0], 8)
        c.close()
        self.assertNotIn('SECRET_TOKEN', str(cloud.snapshot(self.factory, 'new_owner', {})))
        # A new server does not overwrite the original server's key.
        original = self.disk.files[keys[0]]
        other.enable_auto()
        self.assertEqual(self.disk.files[keys[0]], original)
        self.assertEqual(len([k for k in self.disk.files if k.startswith('key-')]), 2)
        other.save(True)
        self.assertNotIn('key-', str(other.versions()['items']))
        for index in range(22):
            self.disk.files['hc-%020d-%s.hcb' % (index, other.config['instance'])] = b'old'
        other.save(True)
        self.assertTrue(all(k in self.disk.files for k in keys))
        self.assertNotIn('OTHER_TOKEN', json.dumps(other.status()))
        self.assertNotIn(other.config['key'], json.dumps(other.status()))

    def test_legacy_password_prompt_and_auto_tampering(self):
        self.enable()
        self.m.save(True)
        name = self.m.versions()['items'][0]['name']
        self.assertEqual(self.m.preview(name), {'password_required': True})
        self.assertIsNone(self.m.staged)
        self.assertEqual(self.m.preview(name, self.password)['ratings'], 1)
        self.m.enable_auto()
        self.m.save(True)
        name = self.m.versions()['items'][0]['name']
        raw = self.disk.files[name]
        self.disk.files[name] = raw[:-1] + bytes([raw[-1] ^ 1])
        with self.assertRaises(cloud.CloudError):self.m.preview(name)
        self.disk.files[name] = raw
        key_name = 'key-' + raw[8:24].hex() + '.json'
        self.disk.files[key_name] = b'{}'
        with self.assertRaises(cloud.CloudError):self.m.preview(name)
        self.assertEqual(self.disk.files[key_name], b'{}', 'never silently regenerate a missing/corrupt key')

    def test_device_flow_poll_rate_and_no_secret_in_status(self):
        result=self.m.start({'client_id':'c'*32,'client_secret':'s'*32})
        self.assertNotIn('device_code',result)
        self.assertEqual(self.m.poll(),{'pending':True})
        self.assertEqual(self.m.poll(),{'pending':True})
        self.assertEqual(self.disk.polls,1)
        self.m.pending['next']=0
        self.assertTrue(self.m.poll()['connected'])
        status=self.m.status()
        self.assertTrue(status['awaiting_choice'])
        self.assertNotIn('SECRET',json.dumps(status))
        self.assertEqual((self.root/'cloud/connection.json').stat().st_mode & 0o777,0o600)
        with self.assertRaises(cloud.CloudError): self.m.save()

    def test_encrypted_roundtrip_and_wrong_password_and_tamper(self):
        document=cloud.snapshot(self.factory,'owner',{'pc':{'values':{'torrserver_url':'http://torrserver.home:8090'},'updated_at':1}})
        salt=b'x'*16;key=cloud.derive(self.password,salt)
        raw=cloud.encrypt(document,key,salt)
        self.assertNotIn(b'torrserver.home',raw)
        recovered,_,_=cloud.decrypt(raw,self.password)
        self.assertEqual(recovered,document)
        for bad, password in [(raw,'wrong password!!'),(raw[:-1]+bytes([raw[-1]^1]),self.password)]:
            with self.assertRaises(cloud.CloudError): cloud.decrypt(bad,password)

    def test_upload_verify_preview_restore_and_old_client_rejected(self):
        self.enable();self.m.devices={'pc':{'values':{'torrserver_url':'http://ts.home:8090'},'updated_at':1}}
        self.m.save(True)
        name=self.m.versions()['items'][0]['name']
        self.assertNotIn('SECRET_TOKEN',str(cloud.decrypt(self.disk.files[name],self.password)[0]))
        c=self.factory()
        with c:c.execute("UPDATE user_ratings SET rating=2")
        c.close()
        preview=self.m.preview(name,self.password)
        self.assertEqual(preview['ratings'],1)
        with self.assertRaises(cloud.CloudError): self.m.apply('wrong')
        self.m.apply(preview['ticket'])
        c=self.factory()
        self.assertEqual(c.execute('SELECT rating FROM user_ratings').fetchone()[0],8)
        self.assertEqual(profiles.state(c,'owner')['values']['homecinema_appearance'],'apple')
        self.assertTrue(profiles.generation(c))
        with self.assertRaises(profiles.Conflict):profiles.save_state(c,'owner',{'device_id':'old','values':{'favorite':{}}})
        c.close()
        self.assertTrue(list((self.root/'cloud/before-restore').glob('*.sqlite3')))
        self.assertEqual(self.m.devices['pc']['values']['torrserver_url'],'http://ts.home:8090')

    def test_restore_to_another_owner_and_schema_rejection_is_atomic(self):
        document=cloud.snapshot(self.factory,'owner',{})
        bad=copy.deepcopy(document);bad['tables']['user_ratings']['columns'].append('injected')
        with self.assertRaises(cloud.CloudError):cloud.restore(self.factory,bad,'owner',self.root/'backups')
        c=self.factory();self.assertEqual(c.execute('SELECT rating FROM user_ratings').fetchone()[0],8);c.close()
        cloud.restore(self.factory,document,'new_owner',self.root/'backups')
        c=self.factory()
        self.assertEqual(c.execute('SELECT profile_id FROM user_ratings').fetchone()[0],'new_owner')
        self.assertEqual(connections.read(c,'new_owner','new_owner')['kp_id'],'123456')
        c.close()

    def test_legacy_migration_column_order_restores_by_name(self):
        document = cloud.snapshot(self.factory, 'owner', {})
        # ALTER TABLE on an old installation appends columns, while a fresh
        # schema declares them in their logical positions. Exercise every table,
        # including profile_id remapping, not only media.
        for table in document['tables'].values():
            order = list(reversed(range(len(table['columns']))))
            table['columns'] = [table['columns'][i] for i in order]
            table['rows'] = [[row[i] for i in order] for row in table['rows']]
        cloud.restore(self.factory, document, 'new_owner', self.root/'backups')
        c = self.factory()
        self.assertEqual(c.execute('SELECT title FROM media WHERE kp_id=42').fetchone()[0], 'Сериал')
        self.assertEqual(c.execute("SELECT rating FROM user_ratings WHERE profile_id='new_owner'").fetchone()[0], 8)
        self.assertEqual(connections.read(c, 'new_owner', 'new_owner')['kp_id'], '123456')
        c.close()

    def test_missing_duplicate_and_unknown_columns_preserve_existing_data(self):
        original = cloud.snapshot(self.factory, 'owner', {})
        for kind in ('missing', 'duplicate', 'unknown'):
            document = copy.deepcopy(original)
            table = document['tables']['media']
            if kind == 'missing':
                table['columns'].pop()
                for row in table['rows']:row.pop()
            elif kind == 'duplicate':table['columns'][-1] = table['columns'][0]
            else:table['columns'][-1] = 'unknown_column'
            with self.subTest(kind=kind), self.assertRaises(cloud.CloudError):
                cloud.restore(self.factory, document, 'owner', self.root/'backups')
            c = self.factory()
            self.assertEqual(c.execute('SELECT rating FROM user_ratings').fetchone()[0], 8)
            c.close()

    def test_corrupt_relations_rollback(self):
        document=cloud.snapshot(self.factory,'owner',{})
        index=document['tables']['user_ratings']['columns'].index('kp_id')
        document['tables']['user_ratings']['rows'][0][index]=999
        with self.assertRaises((cloud.CloudError,sqlite3.IntegrityError)):
            cloud.restore(self.factory,document,'owner',self.root/'backups')
        c=self.factory();self.assertEqual(c.execute('SELECT kp_id FROM user_ratings').fetchone()[0],42);c.close()

    def test_upload_integrity_failure_does_not_mark_success_or_prune(self):
        self.enable();self.disk.broken=True
        with self.assertRaises(cloud.CloudError):self.m.save(True)
        self.assertEqual(self.m.status()['last_save'],0)
        self.assertFalse(any(method=='DELETE' for _,method,_ in self.disk.requests))

    def test_origin_and_signed_url_restrictions(self):
        class H: headers={'Origin':'https://evil.example','Host':'home:9120'}
        self.assertFalse(cloud.allowed_origin(H()))
        H.headers['Origin']='http://home:9118';self.assertTrue(cloud.allowed_origin(H()))
        for url in ('http://yandex.ru/file','https://yandex.ru.evil.example/file','https://127.0.0.1/file'):
            with self.assertRaises(cloud.CloudError):cloud.http(url)

    def test_non_numeric_owner_does_not_create_fake_kp_source(self):
        c=self.factory()
        with c:c.execute('DELETE FROM home_connections')
        c.close()
        document=cloud.snapshot(self.factory,'owner',{})
        cloud.restore(self.factory,document,'new_owner',self.root/'backups')
        c=self.factory()
        self.assertEqual(connections.read(c,'new_owner','new_owner')['kp_id'],'')
        c.close()

    def test_retention_is_per_server_and_restart_keeps_credentials(self):
        self.enable()
        foreign='hc-%020d-%s.hcb' % (1, 'f'*32)
        self.disk.files[foreign]=b'other-house'
        for index in range(22):
            self.disk.files['hc-%020d-%s.hcb' % (index+10,'a'*32)]=b'old'
        self.m.save(True)
        rows=self.m.versions()['items']
        self.assertEqual(len([r for r in rows if r['name'].endswith('a'*32+'.hcb')]),3)
        self.assertIn(foreign,self.disk.files)
        restarted=cloud.Manager(self.root/'cloud',self.factory,'owner',self.disk)
        self.assertTrue(restarted.status()['connected'])
        count=len(self.disk.files)
        restarted.save()
        self.assertEqual(len(self.disk.files),count,'hourly delay survives restart')
        restarted.start({'client_id':'c'*32,'client_secret':'s'*32})
        self.assertFalse(restarted.status()['connected'])
        self.assertFalse(restarted.status()['enabled'],'reconnect cannot write to another account implicitly')

    def test_secondary_kp_import_does_not_replace_owner_ratings(self):
        import kp_sync
        c=self.factory()
        other=profiles.create(c,{'name':'Второй'})['id'];c.close()
        with patch.object(kp_sync,'DB_FILE',self.db), patch.object(kp_sync,'PROFILE_ID','owner'):
            kp_sync.persist_database({'profile_id':other,'public_profile_id':'555','updated_at':1,
                'ratings':[{'kp_id':43,'media_type':'movie','title':'Другой фильм','rating':9}], 'watchlist':[]})
        c=self.factory()
        self.assertEqual(c.execute("SELECT rating FROM user_ratings WHERE profile_id='owner'").fetchone()[0],8)
        self.assertEqual(c.execute('SELECT rating FROM user_ratings WHERE profile_id=?',(other,)).fetchone()[0],9)
        c.close()

    def test_http_routes_reject_foreign_origin_and_do_not_expose_secrets(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import threading
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def review_response(self,code,payload):
                raw=json.dumps(payload).encode()
                self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):cloud.handle(self,outer.factory,'owner',outer.root/'cloud')
            def do_POST(self):cloud.handle(self,outer.factory,'owner',outer.root/'cloud')
            def log_message(self,*args):pass
        with patch.object(cloud,'manager',return_value=self.m):
            server=HTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                req=Request(base+'/cloud/connect.json',data=json.dumps({'client_id':'c'*32,'client_secret':'s'*32}).encode(),headers={'Content-Type':'application/json','Origin':base})
                with urlopen(req,timeout=3) as response:
                    result=json.load(response)
                self.assertEqual(result['user_code'],'USER123');self.assertNotIn('device_code',result)
                with urlopen(base+'/cloud/status.json',timeout=3) as response:
                    self.assertNotIn('ssss',response.read().decode())
                with urlopen(base+'/cloud/qr.svg',timeout=3) as response:
                    self.assertIn(b'<svg',response.read())
                bad=Request(base+'/cloud/disconnect.json',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://evil.example'})
                with self.assertRaises(HTTPError) as caught:urlopen(bad,timeout=3)
                self.assertEqual(caught.exception.code,403)
                self.assertTrue(self.m.config.get('client_secret'),'foreign request cannot disconnect')
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_download_redirect_is_validated_and_oauth_is_not_forwarded(self):
        from urllib.error import HTTPError
        import io
        requests=[]
        class Opener:
            def open(self,request,timeout):
                requests.append(request)
                if len(requests)==1:
                    raise HTTPError(request.full_url,302,'redirect',{'Location':'https://storage.yandex.net/data'},None)
                return io.BytesIO(b'encrypted')
        with patch.object(cloud,'build_opener',return_value=Opener()):
            raw=cloud.http('https://downloader.disk.yandex.ru/file',headers={'Authorization':'OAuth secret'},binary=True)
        self.assertEqual(raw,b'encrypted')
        self.assertFalse(requests[1].has_header('Authorization'))
        class Evil:
            def open(self,request,timeout):
                raise HTTPError(request.full_url,302,'redirect',{'Location':'http://127.0.0.1/private'},None)
        with patch.object(cloud,'build_opener',return_value=Evil()):
            with self.assertRaises(cloud.CloudError):cloud.http('https://downloader.disk.yandex.ru/file',binary=True)

    def test_restoration_wakes_background_import(self):
        self.enable();self.m.save(True)
        preview=self.m.preview(self.m.versions()['items'][0]['name'],self.password)
        connections.REFRESH_EVENT.clear()
        self.m.apply(preview['ticket'])
        self.assertTrue(connections.REFRESH_EVENT.is_set())
        connections.REFRESH_EVENT.clear()

    def test_kp_id_parser(self):
        self.assertEqual(connections.kp_id('https://www.kinopoisk.ru/user/12345/'),'12345')
        for value in ('https://evil.example/user/123/','abc','0','https://kinopoisk.ru/film/123/'):
            with self.assertRaises(ValueError):connections.kp_id(value)


if __name__=='__main__':unittest.main()

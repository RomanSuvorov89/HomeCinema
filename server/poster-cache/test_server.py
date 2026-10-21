import importlib.util
import json
import sqlite3
import struct
import tempfile
import threading
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import server
import install


def png():
    def chunk(kind, payload):
        return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload))
    pixels = b''.join(b'\0' + bytes((i * 31 + y * 17) % 256 for i in range(48)) for y in range(16))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 16, 16, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


class TestPosters(unittest.TestCase):
    def test_installer_preserves_inode_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            target = root / 'lampainit.js'
            original = '// existing plugins\nvar keep = 123;\n'
            target.write_text(original)
            inode = target.stat().st_ino
            (root / '.env').write_text('LAMPAINIT=' + str(target) + '\nPOSTER_BASE=http://server:9121\n')
            (root / 'posters.js').write_text("var base='__POSTER_BASE__';")
            with patch.object(install, 'ROOT', root):
                install.install()
                first = target.read_text()
                install.install()
                self.assertEqual(target.read_text(), first)
                self.assertEqual(first.count(install.BEGIN), 1)
                self.assertTrue(first.endswith(original))
                self.assertEqual(target.stat().st_ino, inode)
                self.assertEqual(len(list(root.glob('*.before-posters-*'))), 1)

    def test_offline_restart_uses_saved_file(self):
        with tempfile.TemporaryDirectory() as root:
            first = server.Posters(root)
            with patch.object(first, 'fetch', return_value=png()) as fetch:
                data, mime, cached = first.get('1178445')
                self.assertFalse(cached)
                self.assertEqual(mime, 'image/png')
                self.assertEqual(fetch.call_count, 1)
            second = server.Posters(root)
            with patch.object(second, 'fetch', side_effect=OSError('offline')) as fetch:
                self.assertEqual(second.get('1178445'), (data, mime, True))
                fetch.assert_not_called()

    def test_concurrent_requests_download_once(self):
        with tempfile.TemporaryDirectory() as root:
            cache = server.Posters(root)
            with patch.object(cache, 'fetch', return_value=png()) as fetch:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results = list(pool.map(cache.get, ['1178445'] * 6))
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(sum(not row[2] for row in results), 1)

    def test_failed_download_not_cached_and_not_repeated_immediately(self):
        with tempfile.TemporaryDirectory() as root:
            cache = server.Posters(root)
            with patch.object(cache, 'fetch', side_effect=OSError('upstream blocked')) as fetch:
                for _ in range(2):
                    with self.assertRaises(OSError):
                        cache.get('1178445')
                self.assertEqual(fetch.call_count, 1)
            self.assertEqual(list(Path(root).glob('*.img')), [])

    def test_html_and_incomplete_images_rejected(self):
        for data in (b'<html>access denied</html>', b'\xff\xd8\xffincomplete'):
            with self.assertRaises(ValueError):
                server.image_type(data)

    def test_download_rejects_html_before_commit(self):
        with tempfile.TemporaryDirectory() as root:
            cache = server.Posters(root)
            def fake_curl(args, **kwargs):
                Path(args[args.index('--output') + 1]).write_bytes(b'<html>' + b'x' * 500 + b'</html>')
                return subprocess_result()
            with patch.object(server.subprocess, 'run', side_effect=fake_curl):
                with self.assertRaises(ValueError):
                    cache.get('1178445')
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_invalid_id_never_fetches(self):
        with tempfile.TemporaryDirectory() as root:
            cache = server.Posters(root)
            with patch.object(cache, 'fetch') as fetch:
                for value in ('../1', '-1', 'abc', '0', 'http://example.com', '1/2'):
                    with self.assertRaises(ValueError):
                        cache.get(value)
                fetch.assert_not_called()

    def test_http_cache_and_unavailable_source(self):
        from urllib.request import urlopen, Request
        from urllib.error import HTTPError
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as root:
            cache = server.Posters(root)
            with patch.object(server, 'POSTERS', cache), patch.object(cache, 'fetch', return_value=png()):
                http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
                worker = threading.Thread(target=http.serve_forever, daemon=True)
                worker.start()
                try:
                    base = 'http://127.0.0.1:' + str(http.server_port)
                    with patch.object(server, 'series_metadata', return_value={'kp_id':'1178445','episodes':[]}):
                        with urlopen(base + '/series/kp/1178445.json') as response:
                            self.assertEqual(response.headers['Content-Type'], 'application/json')
                            self.assertEqual(json.load(response)['episodes'],[])
                    with urlopen(base + '/poster/kp/1178445.jpg') as response:
                        self.assertEqual(response.headers['Content-Type'], 'image/png')
                        self.assertEqual(response.read(), png())
                        etag = response.headers['ETag']
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(Request(base + '/poster/kp/1178445.jpg', headers={'If-None-Match': etag}))
                    self.assertEqual(raised.exception.code, 304)
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(base + '/poster/kp/abc.jpg')
                    self.assertEqual(raised.exception.code, 404)
                finally:
                    http.shutdown()
                    http.server_close()
                    worker.join()

    def test_catalog_exact_ids_and_ambiguous_poster(self):
        import io
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            with sqlite3.connect(path / 'recommender.sqlite3') as conn:
                conn.execute('CREATE TABLE media(kp_id,tmdb_id,imdb_id,media_type,poster_path)')
                conn.executemany('INSERT INTO media VALUES(?,?,?,?,?)', [
                    (1178445, 85552, 'tt8772296', 'tv', '/a.jpg'),
                    (123, 555, 'tt123', 'movie', '/shared.jpg'),
                    (456, 556, 'tt456', 'movie', '/shared.jpg'),
                ])
            with patch.object(server, 'CATALOG', path), patch.object(server, 'urlopen', return_value=io.BytesIO(b'{"card":[]}')):
                catalog = server.Catalog()
                catalog.refresh()
                index = catalog.snapshot()
            self.assertEqual(index['ids']['tv:85552'], '1178445')
            self.assertNotIn('movie:85552', index['ids'])
            self.assertEqual(index['paths']['a.jpg'], '1178445')
            self.assertNotIn('shared.jpg', index['paths'])


class TestSeriesMetadata(unittest.TestCase):
    def test_dates_are_read_only_public_and_filtered(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            with sqlite3.connect(path / 'recommender.sqlite3') as conn:
                conn.execute('CREATE TABLE episode_schedules(kp_id,episodes_json,checked_at)')
                conn.execute('INSERT INTO episode_schedules VALUES(?,?,?)', (42,json.dumps([
                    {'season':2,'episode':3,'date':'2022-01-23','private':'secret'},
                    {'season':2,'episode':4,'date':'2022-02-30'},
                    {'season':2,'episode':5,'date':None},
                    {'season':'2','episode':6,'date':'2022-02-06'},
                ]),123))
            before = (path / 'recommender.sqlite3').read_bytes()
            with patch.object(server,'CATALOG',path):
                self.assertEqual(server.series_metadata('42'), {'kp_id':'42','episodes':[
                    {'season':2,'episode':3,'date':'2022-01-23'}],'checked_at':123})
                self.assertEqual(server.series_metadata('43')['episodes'],[])
                with self.assertRaises(ValueError): server.series_metadata('../42')
            self.assertEqual((path / 'recommender.sqlite3').read_bytes(),before)

    def test_missing_catalog_or_schedule_is_empty(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(server,'CATALOG',Path(root)):
                self.assertEqual(server.series_metadata('42')['episodes'],[])
                with sqlite3.connect(Path(root) / 'recommender.sqlite3'):
                    self.assertEqual(server.series_metadata('42')['episodes'],[])


class subprocess_result:
    returncode = 0
    stderr = b''


class TestSourceChain(unittest.TestCase):
    def test_season_failure_tries_main_before_kinopoisk(self):
        with tempfile.TemporaryDirectory() as root:
            cache=server.Posters(root)
            with patch.object(cache.kinoafisha,'sources',return_value=[('kinoafisha-season','season'),('kinoafisha-main','main')]), patch.object(cache,'download',side_effect=[OSError('gone'),png()]) as download, patch.object(cache,'fetch') as kp:
                self.assertEqual(cache.get('42',2)[0],png())
                self.assertEqual([call.args[0] for call in download.call_args_list],['season','main'])
                kp.assert_not_called()
                self.assertEqual(json.loads((Path(root)/'42.v3.s2.json').read_text())['source'],'kinoafisha-main')

    def test_old_kinopoisk_cache_does_not_block_upgrade_or_mix_seasons(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'42.img').write_bytes(png())
            cache=server.Posters(root)
            with patch.object(cache.kinoafisha,'sources',return_value=[('kinoafisha-season','season')]), patch.object(cache,'download',return_value=png()) as download:
                cache.get('42',1)
                cache.get('42',2)
                cache.get('42',1)
                self.assertEqual(download.call_count,2)
                self.assertTrue((Path(root)/'42.v3.s1.img').is_file())
                self.assertTrue((Path(root)/'42.v3.s2.img').is_file())

    def test_all_kinoafisha_sources_fail_uses_kinopoisk(self):
        with tempfile.TemporaryDirectory() as root:
            cache=server.Posters(root)
            with patch.object(cache.kinoafisha,'sources',return_value=[('kinoafisha-season','season'),('kinoafisha-main','main')]), patch.object(cache,'download',side_effect=OSError('blocked')), patch.object(cache,'fetch',return_value=png()) as kp:
                cache.get('42',2)
                kp.assert_called_once_with('42')

    def test_expired_image_is_rechecked_and_offline_image_survives(self):
        import os
        with tempfile.TemporaryDirectory() as root:
            cache=server.Posters(root)
            with patch.object(cache.kinoafisha,'sources',return_value=[]),patch.object(cache,'fetch',return_value=png()):
                cache.get('42',2)
            os.utime(Path(root)/'42.v3.s2.img',(0,0))
            with patch.object(cache.kinoafisha,'sources',side_effect=OSError('offline')),patch.object(cache,'fetch',side_effect=OSError('offline')):
                self.assertEqual(cache.get('42',2),(png(),'image/png',True))


class TestTmdbCache(unittest.TestCase):
    def test_immutable_path_survives_restart_and_offline(self):
        with tempfile.TemporaryDirectory() as root:
            cache=server.TmdbImages(root)
            with patch.object(cache,'download',return_value=png()) as fetch:
                self.assertEqual(cache.get_image('t/p/w300/frame.jpg'),(png(),'image/png',False))
                self.assertEqual(fetch.call_args.args[0],'https://nl.imagetmdb.com/t/p/w300/frame.jpg')
                self.assertEqual(cache.get_image('t/p/w300/frame.jpg')[-1],True)
                fetch.assert_called_once()
            other=server.TmdbImages(root)
            with patch.object(other,'download',side_effect=OSError('offline')) as fetch:
                self.assertEqual(other.get_image('t/p/w300/frame.jpg'),(png(),'image/png',True))
                fetch.assert_not_called()

    def test_partial_mirror_download_is_discarded_and_next_mirror_is_saved(self):
        with tempfile.TemporaryDirectory() as root:
            cache=server.TmdbImages(root)
            def fake_curl(args, **kwargs):
                output=Path(args[args.index('--output')+1])
                if args[-1].startswith('https://nl.'):
                    output.write_bytes(png()[:200])
                    class Timeout:
                        returncode=28
                        stderr=b'Operation timed out: partial body'
                    return Timeout()
                output.write_bytes(png())
                return subprocess_result()
            with patch.object(server.subprocess,'run',side_effect=fake_curl) as fetch:
                self.assertEqual(cache.get_image('t/p/w300/frame.jpg'),(png(),'image/png',False))
                self.assertEqual([c.args[0][-1] for c in fetch.call_args_list],[
                    'https://nl.imagetmdb.com/t/p/w300/frame.jpg',
                    'https://de.imagetmdb.com/t/p/w300/frame.jpg'])
                for call in fetch.call_args_list:
                    args=call.args[0]
                    self.assertIn('--fail',args)
                    self.assertEqual(args[args.index('--proto')+1],'=https')
                    self.assertNotIn('--insecure',args)
            self.assertEqual(len(list(Path(root).glob('*.img'))),1)
            self.assertEqual(list(Path(root).glob('download-*')),[])
            self.assertEqual(next(Path(root).glob('*.img')).read_bytes(),png())

    def test_invalid_complete_response_tries_next_mirror(self):
        with tempfile.TemporaryDirectory() as root:
            cache=server.TmdbImages(root)
            with patch.object(cache,'download',side_effect=[b'<html>error</html>',png()]) as fetch:
                self.assertEqual(cache.get_image('t/p/w300/frame.jpg')[0],png())
                self.assertEqual(fetch.call_count,2)

    def test_no_html_no_traversal_no_arbitrary_upstreams_and_retry_backoff(self):
        with tempfile.TemporaryDirectory() as root:
            cache=server.TmdbImages(root)
            with patch.object(cache,'download',return_value=b'<html>not an image</html>') as fetch:
                for bad in ['https://evil.test/x.jpg','t/p/w300/../../secret.jpg','t/p/w300/a.jpg?url=http://evil','t/p/w300/a.svg','t/p/w300/%2e%2e.jpg']:
                    with self.assertRaises(ValueError):cache.get_image(bad)
                fetch.assert_not_called()
                with self.assertRaises(OSError):cache.get_image('t/p/w300/missing.jpg')
                with self.assertRaises(OSError):cache.get_image('t/p/w300/missing.jpg')
                self.assertEqual(fetch.call_count,2)
            self.assertEqual(list(Path(root).glob('*.img')),[])

    def test_concurrent_requests_share_download_but_sizes_and_frames_are_separate(self):
        with tempfile.TemporaryDirectory() as root:
            cache=server.TmdbImages(root)
            with patch.object(cache,'download',return_value=png()) as fetch:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    list(pool.map(cache.get_image,['t/p/w300/frame.jpg']*6))
                fetch.assert_called_once()
                cache.get_image('t/p/w500/frame.jpg')
                cache.get_image('t/p/w300/other-frame.jpg')
                self.assertEqual(fetch.call_count,3)
                self.assertEqual(len(list(Path(root).glob('*.img'))),3)

    def test_http_endpoint_returns_image_etag_and_502_never_html_success(self):
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as root:
            cache=server.TmdbImages(root)
            with patch.object(server,'TMDB_IMAGES',cache),patch.object(cache,'download',return_value=png()):
                http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
                worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
                base='http://127.0.0.1:'+str(http.server_port)
                try:
                    address=base+'/tmdb/image/t/p/w300/frame.jpg'
                    with urlopen(address) as response:
                        self.assertEqual(response.read(),png())
                        self.assertIn('immutable',response.headers['Cache-Control'])
                        etag=response.headers['ETag']
                    with self.assertRaises(HTTPError) as error:urlopen(Request(address,headers={'If-None-Match':etag}))
                    self.assertEqual(error.exception.code,304)
                    with self.assertRaises(HTTPError) as error:urlopen(base+'/tmdb/image/https://evil.test/x.jpg')
                    self.assertEqual(error.exception.code,400)
                    with patch.object(cache,'download',return_value=b'HTML error'):
                        with self.assertRaises(HTTPError) as error:urlopen(base+'/tmdb/image/t/p/w300/missing.jpg')
                        self.assertEqual(error.exception.code,502)
                finally:
                    http.shutdown();http.server_close();worker.join()


if __name__ == '__main__':
    unittest.main()

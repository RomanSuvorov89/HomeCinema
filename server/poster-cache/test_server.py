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


class subprocess_result:
    returncode = 0
    stderr = b''


if __name__ == '__main__':
    unittest.main()

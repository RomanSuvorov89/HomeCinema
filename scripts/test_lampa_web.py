import functools
import http.server
import threading
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('web', ROOT / 'prepare-lampa-web.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

class WebTest(unittest.TestCase):
    def archive(self, path, extra=None):
        with zipfile.ZipFile(path, 'w') as bundle:
            for name, content in {'index.html':'<html><body></body></html>',
                                  'app.min.js':'app', 'css/app.css':'body{}', **(extra or {})}.items():
                bundle.writestr('lampa-' + web.DEFAULT_REF + '/' + name, content)

    def test_bootstrap_from_missing_files_preserves_private_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'source.zip'
            self.archive(archive)
            secret = root / 'passwd'
            secret.write_text('private fixture')
            secret.chmod(0o600)
            target = root / 'lampa-main'
            web.install(archive, target, web.DEFAULT_REF)
            self.assertIn('/lampainit.js', (target / 'index.html').read_text())
            self.assertEqual((target / 'tree').read_text(), web.DEFAULT_REF)
            self.assertEqual((target / 'index.html').stat().st_mode & 0o777, 0o644)
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
            with patch.object(web.subprocess, 'run', side_effect=AssertionError('unnecessary download')):
                web.prepare(target)

    def test_reject_broken_download_without_overwriting_existing_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'lampa-main'
            target.mkdir()
            (target / 'index.html').write_text('existing')
            archive = root / 'source.zip'
            self.archive(archive, {'../escape':'bad'})
            with self.assertRaises(ValueError):web.install(archive, target, web.DEFAULT_REF)
            self.assertEqual((target / 'index.html').read_text(), 'existing')
            with zipfile.ZipFile(archive,'w') as bundle:
                bundle.writestr('lampa-' + web.DEFAULT_REF + '/index.html', 'partial')
            with self.assertRaises(ValueError):web.install(archive, target, web.DEFAULT_REF)
            self.assertEqual((target / 'index.html').read_text(), 'existing')

    def test_http_health_rejects_api_only_and_accepts_complete_ui(self):
        spec = importlib.util.spec_from_file_location('health', ROOT / 'check-lampa-web.py')
        health = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(health)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ui = root / 'lampa-main'
            archive = root / 'source.zip'
            self.archive(archive)
            (root / 'version').write_text('api works')
            (root / 'index.html').write_text('api work')
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = 'http://127.0.0.1:' + str(server.server_port)
                with self.assertRaises(ValueError):health.check(base)
                web.install(archive, ui, web.DEFAULT_REF)
                (root / 'index.html').write_text((ui / 'index.html').read_text())
                (root / 'lampainit.js').write_text('plugin fixture')
                health.check(base)
                (ui / 'app.min.js').unlink()
                with self.assertRaises(HTTPError):health.check(base)
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_ref_and_real_healthcheck_covers_ui(self):
        self.assertEqual(web.reference('tree = "' + 'a'*40 + '"'), 'a'*40)
        for path in ('server/install.sh', 'server/healthcheck.sh'):
            self.assertIn('check-lampa-web.py', (ROOT.parent / path).read_text())
        self.assertIn('/lampac/wwwroot/lampa-main', (ROOT.parent / 'server/docker-compose.yml').read_text())

if __name__ == '__main__':unittest.main()

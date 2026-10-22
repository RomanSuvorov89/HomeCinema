import importlib.util
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('apply_profiles',ROOT/'scripts/apply-profiles.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class InstallerTest(unittest.TestCase):
    def test_patch_preserves_config_and_prepares_without_touching_mounted_js(self):
        rec=ROOT/'server/recommender'
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);target=directory/'catalog';target.mkdir();(target/'data').mkdir()
            for name in ('kp_sync.py','kinopoisk.js','client-bootstrap.js','install.py','Dockerfile',
                         'client-defaults.js','track-memory.js'):
                shutil.copy2(rec/name,target/name)
            server=target/'kp_sync.py';server.write_text(server.read_text().replace('PROFILE_ID = os.environ.get("KINOPOISK_PROFILE_ID", "")',
                'PROFILE_ID = os.environ.get("KINOPOISK_PROFILE_ID", "987654")')+'\nCUSTOM_FLAG=True\n')
            client=target/'kinopoisk.js';client.write_text(client.read_text().replace('http://127.0.0.1:9120','http://custom.test:29120'))
            mounted=directory/'lampac/plugins/lampainit.js';mounted.parent.mkdir(parents=True)
            original='function start(){var plugins_add = {initiale}; /* roman-kinopoisk-local */}\n/* preserve sync, theme and posters */'
            mounted.write_text(original);inode=mounted.stat().st_ino
            (directory/'lampac/database').mkdir()
            with sqlite3.connect(directory/'lampac/database/TimeCode.sql') as c:
                c.execute('CREATE TABLE timecodes(item)');c.execute("INSERT INTO timecodes VALUES('keep')")
            def fetch(args,**kwargs):
                name=args[-3].rsplit('/',1)[-1]
                shutil.copy2(rec/name,args[-1])
                return subprocess.CompletedProcess(args,0)
            with patch.object(module.subprocess,'run',side_effect=fetch):
                backup=module.apply(target,mounted,'a'*40)
            self.assertIn('"987654"',server.read_text());self.assertIn('CUSTOM_FLAG=True',server.read_text())
            self.assertIn('http://custom.test:29120', (target/'profiles-client.js').read_text())
            self.assertTrue((target/'cloud_disk.py').is_file())
            self.assertIn('requirements-cloud.txt',(target/'Dockerfile').read_text())
            self.assertIn("if (!storage.get('torrserver_url', ''))",(target/'client-defaults.js').read_text())
            self.assertEqual(server.read_text().count('def import_connected_profile('),1)
            self.assertIn('# homecinema-cloud-worker',server.read_text())
            self.assertEqual(mounted.read_text(),original);self.assertEqual(mounted.stat().st_ino,inode)
            with sqlite3.connect(backup/'database-TimeCode.sql') as c:
                self.assertEqual(c.execute('SELECT item FROM timecodes').fetchone()[0],'keep')
            subprocess.run(['python3',str(target/'install.py'),str(mounted)],check=True,capture_output=True)
            text=mounted.read_text();self.assertIn('preserve sync, theme and posters',text)
            self.assertEqual(text.count('/* homecinema-profiles:start */'),1)
            self.assertLess(text.index('/* homecinema-profiles:start */'),text.index('/* roman-bootstrap-start */'))
            subprocess.run(['python3',str(target/'install.py'),str(mounted)],check=True,capture_output=True)
            self.assertEqual(mounted.read_text(),text);self.assertEqual(mounted.stat().st_ino,inode)

if __name__=='__main__':unittest.main()

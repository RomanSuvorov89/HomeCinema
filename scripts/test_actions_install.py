import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

class InstallActionsTest(unittest.TestCase):
    def test_custom_addresses_and_unrelated_plugins_survive(self):
        spec=importlib.util.spec_from_file_location('apply_actions',ROOT/'scripts/apply-home-actions.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'recommender';target.mkdir()
            rec=ROOT/'server/recommender'
            for name in ('kp_sync.py','review_api.py','kinopoisk.js','install.py','client-defaults.js','client-bootstrap.js','track-memory.js'):
                shutil.copy2(rec/name,target/name)
            kp=target/'kp_sync.py'
            original=kp.read_text().replace('http://127.0.0.1:9118','http://existing-server:29118')+'\nCUSTOM_SETTING="preserve-me"\n'
            kp.write_text(original)
            client=target/'kinopoisk.js'
            client.write_text(client.read_text().replace('http://127.0.0.1:9120','http://existing-server:29120'))
            lampainit=Path(temporary)/'lampainit.js'
            lampainit.write_text('function start(){\nvar plugins_add = {initiale};\n/* roman-kinopoisk-local */\n/* preserve family sync, prefetch, posters and MPV */\n}\n')
            inode=lampainit.stat().st_ino
            run=subprocess.run
            def fetch(args,**kwargs):
                if args[0]=='curl':
                    name=args[args.index('-o')-1].rsplit('/',1)[-1]
                    shutil.copy2(rec/name,args[args.index('-o')+1])
                    return subprocess.CompletedProcess(args,0)
                return run(args,**kwargs)
            with patch.object(module.subprocess,'run',side_effect=fetch):
                module.apply(target,lampainit,'a'*40)
            self.assertIn('http://existing-server:29118',kp.read_text())
            self.assertIn('CUSTOM_SETTING="preserve-me"',kp.read_text())
            self.assertIn('http://existing-server:29120/data.json',client.read_text())
            self.assertIn('preserve family sync, prefetch, posters and MPV',lampainit.read_text())
            self.assertIn('Для меня',lampainit.read_text())
            self.assertEqual(lampainit.stat().st_ino,inode)

if __name__=='__main__':unittest.main()

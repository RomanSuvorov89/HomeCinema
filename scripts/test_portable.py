"""Check actual rendering with non-default ports and alias behavior, without Docker/network."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

class PortableTest(unittest.TestCase):
    def test_render_is_idempotent_and_configured(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'project'
            shutil.copytree(ROOT,root,ignore=shutil.ignore_patterns('data','__pycache__','.git'))
            lampac=root/'server/data/lampac';lampac.mkdir(parents=True)
            (lampac/'lampainit.upstream.js').write_text('function start() {\nvar plugins_add = {initiale};\n}\n')
            env=dict(os.environ,PUBLIC_LAMPAC_URL='http://cinema.test:19118',PUBLIC_RECOMMENDER_URL='http://cinema.test:19120',PUBLIC_TORRSERVER_URL='http://cinema.test:18090',PUBLIC_POSTER_URL='http://cinema.test:19121',LAMPAC_SYNC_ID='test-family',ENABLE_COMMUNITY_PLUGINS='0')
            cmd=['python3',str(root/'server/scripts/render.py')]
            subprocess.run(cmd,env=env,check=True,capture_output=True)
            target=lampac/'lampainit.js';before=target.read_text();inode=target.stat().st_ino
            for expected in ('http://cinema.test:19121','http://cinema.test:19120','http://cinema.test:18090','http://cinema.test:19118/sync/js/test-family','items_line','romanFamilyWatchV1'):
                self.assertIn(expected,before)
            self.assertNotIn('127.0.0.1:9120',before)
            # Lampac substitutes this placeholder before serving JS.
            js=before.replace('{initiale}','[]')
            output=lampac/'syntax.js';output.write_text(js)
            subprocess.run(['node','--check',str(output)],check=True,capture_output=True)
            subprocess.run(cmd,env=env,check=True,capture_output=True)
            self.assertEqual(before,target.read_text());self.assertEqual(inode,target.stat().st_ino)
            # Legacy component tests use loopback fixtures, independently of configured-port checks.
            env.update(PUBLIC_LAMPAC_URL='http://127.0.0.1:9118', PUBLIC_RECOMMENDER_URL='http://127.0.0.1:9120', PUBLIC_TORRSERVER_URL='http://127.0.0.1:8090', PUBLIC_POSTER_URL='http://127.0.0.1:9121')
            subprocess.run(cmd,env=env,check=True,capture_output=True)
            # Render production build context locally for the existing component tests.
            for p in (root/'server/recommender').glob('*.js'):
                if p.name in ('client-defaults.js','client-bootstrap.js','kinopoisk.js','profiles-client.js'):
                    shutil.copy2(p,ROOT/'server/recommender'/p.name)

    def test_alias_uses_correct_disk_cache(self):
        spec=importlib.util.spec_from_file_location('posters',ROOT/'server/poster-cache/server.py')
        with patch.object(sys, 'path', [str(ROOT/'server/poster-cache')] + sys.path):
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'poster-overrides.json').write_text(json.dumps({'45003510':'5003510'}))
            cache=module.Posters(root/'posters')
            # Sufficient for the service's complete JPEG validation.
            data=b'\xff\xd8\xff'+b'x'*200+b'\xff\xd9'
            with patch.object(cache,'fetch',return_value=data) as fetch:
                self.assertEqual(cache.get('45003510')[0],data)
                fetch.assert_called_once_with('5003510')
                self.assertTrue((root/'posters/5003510.v3.s0.img').is_file())
                self.assertTrue(cache.get('45003510')[2])

if __name__=='__main__': unittest.main()

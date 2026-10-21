"""Exercise UCI commit/rollback semantics without changing the host network."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/fix-podkop-tmdb.sh'

UCI = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
config=Path(os.environ['HC_PODKOP_CONFIG']); pending=config.with_suffix('.pending')
args=[a for a in sys.argv[1:] if a!='-q']; action=args[0]
data=json.loads((pending if pending.exists() else config).read_text())
if action=='get':
    key=args[1]
    if key not in data: sys.exit(1)
    value=data[key]; print(' '.join(value) if isinstance(value,list) else value)
elif action=='changes':
    if pending.exists(): print('pending edits')
elif action in ('set','add_list'):
    key,value=args[1].split('=',1)
    if action=='set': data[key]=value
    else: data.setdefault(key,[]).append(value)
    pending.write_text(json.dumps(data))
elif action=='commit':
    config.write_text(json.dumps(data)); pending.unlink(missing_ok=True)
elif action=='revert': pending.unlink(missing_ok=True)
else: sys.exit(2)
'''

class RouterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.config = self.path/'podkop'
        self.values = {
            'podkop.main.connection_type':'vpn', 'podkop.main.interface':'awg0',
            'podkop.main.user_domain_list_type':'text',
            'podkop.main.user_domains_text':'youtube.com\n// themoviedb.org\ntmdb.com',
            'podkop.main.mixed_proxy_enabled':'0',
            'podkop.main.domain_resolver_enabled':'0',
            'podkop.settings.dns_server':'77.88.8.8',
            'podkop.settings.config_path':str(self.path/'sing-box.json'),
        }
        self.config.write_text(json.dumps(self.values))
        self.program = self.path/'program'; self.program.write_text('domain_resolver_enabled')
        self.bin = self.path/'bin'; self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'],
            HC_PODKOP_CONFIG=str(self.config), HC_PODKOP_INIT=str(self.bin/'restart'),
            HC_PODKOP_PROGRAM=str(self.program), HC_PODKOP_BACKUPS=str(self.path/'backups'),
            HC_PODKOP_LOCK=str(self.path/'lock'), HC_RESTART_LOG=str(self.path/'restarts'))
        self.executable('uci', UCI)
        self.executable('sing-box', '#!/bin/sh\nexit 0\n')
        self.executable('restart', '#!/bin/sh\necho restart >> "$HC_RESTART_LOG"\n')

    def executable(self,name,text):
        p=self.bin/name; p.write_text(text); p.chmod(0o755)

    def run_script(self,*args):
        return subprocess.run(['sh',str(SCRIPT),*args],env=self.env,text=True,capture_output=True)

    def test_preserves_rules_interface_dns_and_disabled_proxy_is_idempotent(self):
        first=self.run_script(); self.assertEqual(first.returncode,0,first.stderr)
        data=json.loads(self.config.read_text())
        text=data['podkop.main.user_domains_text']
        self.assertTrue(text.startswith(self.values['podkop.main.user_domains_text']))
        self.assertEqual(text.splitlines().count('themoviedb.org'),1,'comment must not count as an active rule')
        self.assertEqual(data['podkop.main.interface'],'awg0')
        self.assertEqual(data['podkop.main.mixed_proxy_enabled'],'0')
        self.assertEqual(data['podkop.settings.dns_server'],'77.88.8.8')
        self.assertEqual(data['podkop.main.domain_resolver_dns_server'],'1.1.1.1')
        second=self.run_script(); self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(json.loads(self.config.read_text()),data)
        saved=Path(next(line.split(': ',1)[1] for line in first.stdout.splitlines() if line.startswith('Резервная копия: ')))
        result=self.run_script('--rollback',str(saved)); self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(self.config.read_text()),self.values)

    def test_dynamic_domain_list_stays_dynamic(self):
        self.values['podkop.main.user_domain_list_type']='dynamic'
        self.values['podkop.main.user_domains']=['example.test','tmdb.org']
        self.config.write_text(json.dumps(self.values))
        result=self.run_script(); self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(self.config.read_text())
        self.assertEqual(data['podkop.main.user_domain_list_type'],'dynamic')
        self.assertEqual(data['podkop.main.user_domains'],['example.test','tmdb.org','themoviedb.org','tmdb-image-prod.b-cdn.net'])

    def test_failed_restart_restores_original_config(self):
        self.executable('restart', '#!/bin/sh\nif [ ! -f "$HC_RESTART_LOG" ]; then touch "$HC_RESTART_LOG"; exit 1; fi\n')
        original=self.config.read_bytes()
        result=self.run_script(); self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.config.read_bytes(),original)
        self.assertFalse((self.path/'lock').exists())
        self.assertFalse(self.config.with_suffix('.pending').exists())

    def test_invalid_generated_config_restores_original(self):
        self.executable('sing-box', '#!/bin/sh\nexit 1\n')
        original=self.config.read_bytes()
        result=self.run_script(); self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.config.read_bytes(),original)
        self.assertFalse((self.path/'lock').exists())

    def test_pending_edits_are_not_committed_or_discarded(self):
        pending=self.config.with_suffix('.pending'); pending.write_text(json.dumps(self.values))
        original=self.config.read_bytes()
        result=self.run_script(); self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.config.read_bytes(),original)
        self.assertTrue(pending.exists())
        self.assertFalse((self.path/'backups').exists())

if __name__=='__main__': unittest.main()

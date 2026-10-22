import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj

prepare=module('prepare-first-run');ports=module('preflight-ports')

class FirstRunTest(unittest.TestCase):
    def test_private_configuration_without_kp_is_stable_on_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);shutil.copytree(ROOT/'config',root/'config',ignore=shutil.ignore_patterns('stack.env','profiles.json','rating-scale.json'))
            with patch.dict(os.environ,{'HC_PUBLIC_HOST':'cinema.home'}):prepare.prepare(root)
            profiles=json.loads((root/'config/profiles.json').read_text())
            profile=profiles['profiles'][0]
            self.assertRegex(profile['home_profile_id'],r'^local_[a-f0-9]{24}$')
            self.assertEqual(profile['kinopoisk_profile_id'],'')
            env=(root/'config/stack.env').read_text()
            self.assertIn('PUBLIC_TORRSERVER_URL=http://cinema.home:8090',env)
            self.assertNotIn('CHANGE_ME',env)
            for path in (root/'config/stack.env',root/'config/profiles.json'):
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with patch.dict(os.environ,{'HC_PUBLIC_HOST':'changed.home'}):prepare.prepare(root)
            self.assertEqual(env,(root/'config/stack.env').read_text())
            self.assertEqual(profiles,json.loads((root/'config/profiles.json').read_text()))

    def test_partial_configuration_and_invalid_host_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config').mkdir();target=root/'config/stack.env';target.write_text('keep')
            with self.assertRaises(ValueError):prepare.prepare(root)
            self.assertEqual(target.read_text(),'keep')
        for value in ('evil;command','http://cinema.home','a..b','host:9118'):
            with patch.dict(os.environ,{'HC_PUBLIC_HOST':value}):
                with self.assertRaises(ValueError):prepare.detect_host()

    def test_busy_foreign_port_refuses_without_stopping_anything(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            port=listener.getsockname()[1]
            free=[]
            for _ in range(3):
                sock=socket.socket();sock.bind(('127.0.0.1',0));free.append(sock)
            values={'STACK_NAME':'test','LAMPAC_PORT':str(port),**dict(zip(('TORRSERVER_PORT','RECOMMENDER_PORT','POSTER_PORT'),(str(s.getsockname()[1]) for s in free)))}
            for sock in free:sock.close()
            with patch.dict(os.environ,values),patch.object(ports,'owned_ports',return_value=set()):
                with self.assertRaisesRegex(ValueError,'занят другим сервисом'):ports.check(ROOT/'server',['docker'])

    def test_only_same_compose_directory_can_reuse_ports(self):
        record={'labels':{'com.docker.compose.project':'test','com.docker.compose.project.working_dir':str(ROOT/'server')},'ports':{'9118/tcp':[{'HostPort':'9118'}]}}
        def output(args,**kw):return 'container-id' if args[-2:]==['ps','-q'] else json.dumps(record)
        with patch.dict(os.environ,{'STACK_NAME':'test'}),patch.object(ports.subprocess,'check_output',side_effect=output):
            self.assertEqual(ports.owned_ports(ROOT/'server',['docker']),{9118})
            record['labels']['com.docker.compose.project']='server'
            self.assertEqual(ports.owned_ports(ROOT/'server',['docker']),{9118},'default compose project name is recognized on resume')
            record['labels']['com.docker.compose.project.working_dir']='/another/stack'
            self.assertEqual(ports.owned_ports(ROOT/'server',['docker']),set())

    def test_one_command_runs_existing_installer_and_resumes_without_data_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);bin_dir=directory/'bin';bin_dir.mkdir();target=directory/'installed'
            def script(name,body):
                p=bin_dir/name;p.write_text('#!/usr/bin/env bash\nset -eu\n'+body);p.chmod(0o755)
            script('git', '''if [[ "$1" == clone ]]; then
  "${TEST_PYTHON}" - "$TEST_REPOSITORY" "$3" <<'END'
import sys,shutil
from pathlib import Path
shutil.copytree(sys.argv[1],sys.argv[2],dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','data','__pycache__','stack.env','profiles.json','rating-scale.json','.runtime.env'))
Path(sys.argv[2],'.git').mkdir()
END
elif [[ "$*" == *"config --get remote.origin.url" ]]; then echo 'https://github.com/RomanSuvorov89/HomeCinema.git';
elif [[ "$*" == *"rev-parse"* ]]; then echo aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa;
fi
echo "git $*" >> "$TEST_LOG"
''')
            script('python3','if [[ "$1" == *preflight-ports.py ]]; then exit 0; fi\nexec "$TEST_PYTHON" "$@"\n')
            for name in ('pacman','apt-get','systemctl','usermod'):script(name,'echo "'+name+' $*" >> "$TEST_LOG"\n')
            script('sudo','exec "$@"\n')
            script('docker', '''echo "docker $*" >> "$TEST_LOG"
if [[ "$1" == cp ]]; then
  echo 'function start() { var plugins_add = {initiale}; }' > "$3"
elif [[ "$1" == create ]]; then echo temporary-id;
fi
''')
            script('curl','echo \'{"ok":true,"database":true}\'\n')
            env=dict(os.environ,PATH=str(bin_dir)+':'+os.environ['PATH'],HC_INSTALL_DIR=str(target),HC_PUBLIC_HOST='cinema.home',TEST_PYTHON=sys.executable,TEST_REPOSITORY=str(ROOT),TEST_LOG=str(directory/'commands.log'))
            result=subprocess.run(['bash',str(ROOT/'install.sh')],env=env,capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('HOME_PROFILE_ID=local_', (target/'server/.runtime.env').read_text())
            runtime=(target/'config/stack.env').read_text()
            secret=target/'server/data/recommender/cloud/connection.json';secret.parent.mkdir(parents=True);secret.write_text('keep-credentials')
            second=subprocess.run(['bash',str(ROOT/'install.sh')],env=env,capture_output=True,text=True,timeout=40)
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertEqual(secret.read_text(),'keep-credentials')
            self.assertEqual((target/'config/stack.env').read_text(),runtime)
            commands=(directory/'commands.log').read_text()
            self.assertIn('fetch origin main',commands)
            self.assertIn('update-ref refs/homecinema/backups/',commands)
            self.assertIn('checkout --detach aaaaaaaaaa',commands)
            self.assertTrue(list((target/'server/backups').glob('home-cinema-backup-*.tar.gz')))
            self.assertIn('up -d --build',commands)
            self.assertNotIn(' down',commands)
            self.assertNotIn('volume rm',commands)

    def test_real_git_update_keeps_private_state_and_prior_source(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);origin=base/'origin';origin.mkdir();target=base/'home'
            def git(*args):
                return subprocess.check_output(['git','-C',str(origin),*args],text=True,stderr=subprocess.STDOUT).strip()
            git('init','-b','main');git('config','user.name','Test');git('config','user.email','test@example.invalid')
            (origin/'scripts').mkdir();(origin/'server').mkdir()
            (origin/'.gitignore').write_text('/config/\n/server/.runtime.env\n/server/data/\n/server/backups/\n')
            (origin/'VERSION').write_text('1')
            (origin/'scripts/prepare-first-run.py').write_text('''import sys
from pathlib import Path
r=Path(sys.argv[1]);(r/'config').mkdir(exist_ok=True)
p=r/'config/stack.env'
if not p.exists():p.write_text('private-config')
''')
            (origin/'server/install.sh').write_text('''set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/server/data"
touch "$ROOT/server/.runtime.env"
cat "$ROOT/VERSION" > "$TEST_LOG"
''')
            (origin/'server/backup.sh').write_text('''set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/server/backups"
cp "$ROOT/server/data/private" "$ROOT/server/backups/private"
''')
            (origin/'server/healthcheck.sh').write_text('exit 0\n')
            (origin/'scripts/update-profiles.sh').write_text('printf "legacy:%s:%s" "$1" "$2" > "$TEST_LOG"\n')
            git('add','.');git('commit','-m','first');old=git('rev-parse','HEAD')
            env=dict(os.environ,HC_INSTALL_DIR=str(target),HC_LEGACY_DIR=str(base/'legacy'),
                HC_LAMPAINIT=str(base/'lampainit.js'),HC_PUBLIC_HOST='cinema.home',TEST_LOG=str(base/'version'),
                GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='url.'+origin.as_uri()+'/.insteadOf',
                GIT_CONFIG_VALUE_0='https://github.com/RomanSuvorov89/HomeCinema.git')
            # Only Docker privilege detection is stubbed; clone, fetch, checkout and refs are real Git.
            bin_dir=base/'bin';bin_dir.mkdir();docker=bin_dir/'docker';docker.write_text('#!/bin/sh\nexit 0\n');docker.chmod(0o755)
            env['PATH']=str(bin_dir)+':'+env['PATH']
            def run():return subprocess.run(['bash',str(ROOT/'install.sh')],env=env,capture_output=True,text=True,timeout=15)
            first=run();self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            (target/'server/data/private').write_text('history-and-secret')
            (origin/'VERSION').write_text('2');git('add','VERSION');git('commit','-m','second');new=git('rev-parse','HEAD')
            second=run();self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertEqual((base/'version').read_text(),'2')
            self.assertEqual((target/'config/stack.env').read_text(),'private-config')
            self.assertEqual((target/'server/data/private').read_text(),'history-and-secret')
            self.assertEqual((target/'server/backups/private').read_text(),'history-and-secret')
            self.assertEqual(subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip(),new)
            refs=subprocess.check_output(['git','-C',str(target),'show-ref'],text=True)
            self.assertIn(old+' refs/homecinema/backups/',refs)
            (target/'VERSION').write_text('custom-work')
            refused=run();self.assertNotEqual(refused.returncode,0)
            self.assertEqual((target/'VERSION').read_text(),'custom-work')
            self.assertEqual((base/'version').read_text(),'2','refused update never starts services')
            # A separate installation is updated in place and never initializes a second stack.
            legacy=base/'legacy';legacy.mkdir();(legacy/'kp_sync.py').write_text('existing')
            (base/'lampainit.js').write_text('mounted')
            env['HC_INSTALL_DIR']=str(base/'legacy-checkout')
            upgraded=run();self.assertEqual(upgraded.returncode,0,upgraded.stdout+upgraded.stderr)
            self.assertEqual((base/'version').read_text(),'legacy:'+new+':'+str(legacy))
            self.assertFalse((base/'legacy-checkout/config/stack.env').exists())


class LocalBootstrapServerTest(unittest.TestCase):
    def test_actual_python_server_starts_without_kp_and_serves_restore_menu(self):
        # Run the real main/Handler/schema on a fresh directory; external workers are disabled.
        import runpy
        import threading
        from http.server import ThreadingHTTPServer as RealServer
        from urllib.request import urlopen
        sys.path.insert(0,str(ROOT/'server/recommender'))
        import cloud_disk,home_cache
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);config=data/'home.json';config.write_text('{"kinopoisk_enabled":false}')
            owner='local_'+'a'*24
            env={'HOME_PROFILE_ID':owner,'KINOPOISK_PROFILE_ID':'','SERVE':'1',
                'DATA_FILE':str(data/'kinopoisk.json'),'DB_FILE':str(data/'recommender.sqlite3'),
                'HOME_CACHE_DB':str(data/'home-cache.sqlite3'),'HOME_CACHE_CONFIG':str(config)}
            class Server(RealServer):
                def __init__(self,address,handler):super().__init__(('127.0.0.1',0),handler)
                def serve_forever(self):
                    thread=threading.Thread(target=super().serve_forever,daemon=True);thread.start()
                    try:
                        base='http://127.0.0.1:'+str(self.server_port)
                        for path in ('/profiles.json','/data.json','/connections.json','/cloud/status.json'):
                            with urlopen(base+path,timeout=3) as response:payload=json.load(response)
                            if path=='/profiles.json':outer.assertEqual(payload['owner_id'],owner)
                            if path=='/connections.json':outer.assertEqual(payload['kp_id'],'')
                            if path=='/data.json':outer.assertEqual(payload['ratings'],[])
                            if path=='/cloud/status.json':outer.assertTrue(payload['needs_setup'])
                    finally:self.shutdown();self.server_close();thread.join()
            outer=self
            def manager(factory,profile,root):return cloud_disk.Manager(root,factory,profile)
            try:
                with patch.dict(os.environ,env),patch('http.server.ThreadingHTTPServer',Server),patch.object(home_cache,'start_worker'),patch.object(cloud_disk,'manager',side_effect=manager):
                    runpy.run_path(str(ROOT/'server/recommender/kp_sync.py'),run_name='__main__')
                self.assertTrue((data/'recommender.sqlite3').is_file())
                self.assertEqual(json.loads((data/'kinopoisk.json').read_text())['profile_id'],owner)
            finally:sys.path.pop(0)

if __name__=='__main__':unittest.main()

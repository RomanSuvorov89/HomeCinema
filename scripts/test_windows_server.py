"""Exercise the Linux controller using a disposable Docker executable."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
CONTROLLER=ROOT/'windows/wsl-server-control.sh'

class ServerControllerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.repo=self.root/"project with spaces and 'quote"
        (self.repo/'server').mkdir(parents=True)
        self.bin=self.root/'bin';self.bin.mkdir()
        self.log=self.root/'docker.jsonl'
        fake=self.bin/'docker'
        fake.write_text('#!/usr/bin/env python3\nimport os,json,sys\nwith open(os.environ["DOCKER_TEST_LOG"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\nprint("docker test response")\n')
        fake.chmod(0o755)
        self.env=dict(os.environ,PATH=str(self.bin)+os.pathsep+os.environ['PATH'],DOCKER_TEST_LOG=str(self.log))
    def tearDown(self):self.temp.cleanup()
    def call(self,action,target='home-cinema-lampac'):
        result=subprocess.run(['bash',str(CONTROLLER),action,str(self.repo),target],env=self.env,capture_output=True,text=True)
        calls=[json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result,calls
    def test_start_stop_and_restart_only_compose_project(self):
        for action,tail in [('start',['up','-d','--no-build','--pull','never']),('stop',['stop']),('restart',['restart'])]:
            with self.subTest(action=action):
                if self.log.exists():self.log.unlink()
                result,calls=self.call(action)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(calls,[['compose','--env-file','server/.runtime.env','-f','server/docker-compose.yml']+tail])
    def test_status_is_read_only_and_includes_stopped_containers(self):
        result,calls=self.call('status')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([args[0] for args in calls],['info','ps'])
        self.assertIn('-a',calls[1])
    def test_logs_bounded_and_foreign_container_rejected(self):
        result,calls=self.call('logs')
        self.assertEqual(result.returncode,0)
        self.assertEqual(calls,[['logs','--timestamps','--tail','150','home-cinema-lampac']])
        self.log.unlink()
        for action in ('logs','restart-container'):
            result,calls=self.call(action,'another-project')
            self.assertEqual(result.returncode,2)
            self.assertEqual(calls,[])
    def test_unknown_action_rejected_without_docker(self):
        result,calls=self.call('delete')
        self.assertEqual(result.returncode,2)
        self.assertEqual(calls,[])
    def test_resources_and_disk_are_read_only(self):
        for action,command in [('resources','stats'),('disk','system')]:
            if self.log.exists():self.log.unlink()
            result,calls=self.call(action)
            self.assertEqual(result.returncode,0)
            self.assertEqual(calls[0][0],command)
            if action=='disk':self.assertEqual(calls,[['system','df']])

if __name__=='__main__':unittest.main()

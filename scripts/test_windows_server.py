"""Read-only Linux inspection and explicitly selected Docker mutations."""
import json,os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CONTROLLER=ROOT/'windows/wsl-server-control.sh'
class LinuxControllerTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.bin=self.root/'bin';self.bin.mkdir();self.log=self.root/'calls'
  fake=self.bin/'docker'
  fake.write_text('#!/usr/bin/env python3\nimport os,json,sys\nwith open(os.environ["DOCKER_TEST_LOG"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\nprint("other-project-worker" if sys.argv[1:]==["ps","-a","--format","{{.Names}}"] else "test response")\n');fake.chmod(0o755)
  self.env=dict(os.environ,PATH=str(self.bin)+os.pathsep+os.environ['PATH'],DOCKER_TEST_LOG=str(self.log))
 def tearDown(self):self.tmp.cleanup()
 def call(self,action,target='other-project-worker'):
  if self.log.exists():self.log.unlink()
  result=subprocess.run(['bash',str(CONTROLLER),action,target],env=self.env,capture_output=True,text=True,cwd='/tmp')
  calls=[json.loads(s) for s in self.log.read_text().splitlines()] if self.log.exists() else []
  return result,calls
 def test_all_projects_can_be_selected_without_compose(self):
  for action,cmd in [('start-container','start'),('stop-container','stop'),('restart-container','restart')]:
   result,calls=self.call(action)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertEqual(calls,[['inspect','--type','container','other-project-worker'],[cmd,'other-project-worker']])
 def test_status_reads_linux_and_all_containers_without_project_directory(self):
  result,calls=self.call('status')
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertIn('Linux:',result.stdout);self.assertIn('Memory:',result.stdout)
  self.assertIn('__WSL_CONTAINER_NAMES__',result.stdout)
  self.assertTrue(all(x[0] in ('info','ps') for x in calls))
  self.assertIn(['ps','-a','--format','{{.Names}}'],calls)
 def test_logs_bounded(self):
  result,calls=self.call('logs')
  self.assertEqual(result.returncode,0)
  self.assertEqual(calls[-1],['logs','--timestamps','--tail','150','other-project-worker'])
 def test_invalid_name_cannot_inject_docker_flags_or_shell(self):
  for target in ('--all','x;reboot','$(touch /tmp/unsafe)',''):
   result,calls=self.call('restart-container',target)
   self.assertEqual(result.returncode,2);self.assertEqual(calls,[])
 def test_unknown_actions_and_project_wide_stop_rejected(self):
  for action in ('stop','start','restart','delete'):
   result,calls=self.call(action)
   self.assertEqual(result.returncode,2);self.assertEqual(calls,[])
 def test_resources_read_only(self):
  for action,cmd in [('resources','stats'),('disk','system')]:
   result,calls=self.call(action)
   self.assertEqual(result.returncode,0);self.assertEqual(calls[0][0],cmd)
if __name__=='__main__':unittest.main()

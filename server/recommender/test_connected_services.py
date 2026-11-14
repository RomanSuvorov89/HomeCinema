import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import kp_sync,connections

class ConnectedServicesTest(unittest.TestCase):
 def test_local_browser_connects_second_profile_and_foreign_origin_is_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'test.db'
   def factory():
    c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
   c=factory();c.executescript(Path('schema.sql').read_text())
   c.executemany('INSERT INTO profiles VALUES(?,?,?,?,?)',[('owner','Main','',0,0),('wife','Second','',0,0)])
   connections.ensure(c);c.execute("INSERT INTO home_connections(profile_id,kp_id) VALUES('owner','111')");c.commit();c.close()
   class Handler(kp_sync.Handler):
    def log_message(self,*args):pass
   with patch.object(kp_sync,'direct_connection',factory),patch.object(kp_sync,'PROFILE_ID','owner'),patch.object(connections,'start_import') as queued:
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def request(origin,body=None,profile='wife'):
     req=Request(base+'/connections.json?id='+profile,data=json.dumps(body).encode() if body else None,headers={'Origin':origin,'Content-Type':'application/json'})
     with urlopen(req,timeout=3) as response:return json.load(response)
    try:
     self.assertEqual(request('http://localhost:9118')['kp_id'],'')
     self.assertTrue(request('http://localhost:9118',{'profile_id':'wife','kp_id':'222'})['queued'])
     self.assertEqual(queued.call_args.args[1],'wife')
     self.assertEqual(request('http://localhost:9118')['kp_id'],'222')
     self.assertEqual(request('http://127.0.0.1:9118',profile='owner')['kp_id'],'111')
     with self.assertRaises(HTTPError) as error:request('https://evil.example',{'profile_id':'wife','kp_id':'333'})
     self.assertEqual(error.exception.code,403)
     self.assertEqual(request('http://localhost:9118')['kp_id'],'222')
     self.assertEqual(queued.call_count,1)
    finally:server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()

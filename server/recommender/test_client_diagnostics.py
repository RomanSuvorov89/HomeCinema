import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
import kp_sync

class DiagnosticTest(unittest.TestCase):
    def test_home_get_is_read_only(self):
        from unittest.mock import patch
        handler = kp_sync.Handler.__new__(kp_sync.Handler)
        handler.path='/home.json'
        responses=[]
        handler.review_response=lambda code,data:responses.append((code,data))
        class FakeCache:
            def snapshot(self,profile): return {"profile_id":profile,"rows":[]}
        import sqlite3
        connection=sqlite3.connect(':memory:')
        connection.set_authorizer(lambda action,*args: sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION) else sqlite3.SQLITE_DENY)
        with patch.object(kp_sync,'HOME_CACHE',FakeCache()), patch.object(kp_sync,'direct_connection',return_value=connection), patch.object(kp_sync,'write_recommendation_reports',side_effect=AssertionError('Unexpected recalculation')):
            handler.do_GET()
        self.assertEqual(responses[0][0],200)

    def test_post_get_without_database(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), kp_sync.Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = 'http://127.0.0.1:%s/client-diagnostics.json' % server.server_port
            request = urllib.request.Request(url, data=json.dumps({'stage':'test','message':'test error'}).encode(), headers={'Content-Type':'text/plain'})
            with urllib.request.urlopen(request) as response:
                self.assertTrue(json.load(response)['ok'])
            with urllib.request.urlopen(url) as response:
                self.assertEqual(json.load(response)['events'][-1]['message'], 'test error')
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
        finally:
            server.shutdown()
            server.server_close()

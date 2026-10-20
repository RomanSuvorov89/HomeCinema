import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import kp_sync
import review_api


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'review.sqlite3'
        c = self.connect()
        c.executescript(Path('schema.sql').read_text())
        c.execute("INSERT INTO profiles VALUES('owner','Owner','',0,0)")
        c.execute("INSERT INTO profiles VALUES('other','Other','',0,0)")
        c.execute("INSERT INTO media(kp_id,media_type,title) VALUES(42,'movie','Test')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',42,7)")
        c.commit()
        c.close()

    def connect(self):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def tearDown(self):
        self.tmp.cleanup()

    def test_profile_feedback_replace_clear_and_rating_preserved(self):
        c = self.connect()
        review_api.save_feedback(c, 'owner', {'kp_id':42, 'status':'want'})
        review_api.save_feedback(c, 'other', {'kp_id':42, 'status':'seen'})
        review_api.save_feedback(c, 'owner', {'kp_id':42, 'status':'not_interested'})
        self.assertEqual(c.execute("SELECT status FROM recommendation_feedback WHERE profile_id='owner'").fetchone()[0], 'not_interested')
        review_api.save_feedback(c, 'owner', {'kp_id':42, 'status':'clear'})
        self.assertEqual(c.execute('SELECT count(*) FROM recommendation_feedback').fetchone()[0], 1)
        self.assertEqual(c.execute('SELECT rating FROM user_ratings').fetchone()[0], 7)
        c.close()

    def test_hidden_title_is_filtered_from_cached_home_without_changing_rating(self):
        import copy
        raw={'rows':[{'kind':kind,'results':[{'kinopoisk_id':'42','title':'Test'},{'kinopoisk_id':'43','title':'Other'}]} for kind in ('continue','ai','now','watch')]}
        class FakeCache:
            def snapshot(self,profile):return copy.deepcopy(raw)
        c=self.connect()
        review_api.save_feedback(c,'owner',{'kp_id':42,'status':'not_interested'})
        result=review_api.home_snapshot(c,FakeCache(),'owner')
        self.assertEqual(result['hidden_ids'],['42'])
        self.assertEqual([len(r['results']) for r in result['rows']],[1,1,1,2])
        self.assertEqual(len(review_api.home_snapshot(c,FakeCache(),'other')['rows'][0]['results']),2)
        review_api.save_feedback(c,'owner',{'kp_id':42,'status':'clear'})
        self.assertEqual(len(review_api.home_snapshot(c,FakeCache(),'owner')['rows'][0]['results']),2)
        self.assertEqual(c.execute('SELECT rating FROM user_ratings').fetchone()[0],7)
        c.close()

    def test_actual_http_save_and_read_and_validation(self):
        report_file = Path(self.tmp.name) / 'recommendations.json'
        report_file.write_text(json.dumps({'groups':[{'code':'for_me','items':[{
            'kp_id':42,'title':'Test','predicted_rating':7.12,
            'reasons':{'positive_features':[{'type':'country','name':'Unused'},{'type':'genre','name':'Fantasy'}]}
        }]}]}))
        with patch.object(kp_sync, 'direct_connection', self.connect), patch.object(kp_sync, 'PROFILE_ID', 'owner'), patch.object(kp_sync, 'RECOMMENDATIONS_JSON_FILE', report_file):
            server = ThreadingHTTPServer(('127.0.0.1', 0), kp_sync.Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                req = urllib.request.Request(base+'/review-feedback.json', data=json.dumps({'kp_id':42,'status':'want','profile_id':'other'}).encode(), headers={'Content-Type':'application/json'})
                self.assertTrue(json.load(urllib.request.urlopen(req))['ok'])
                data = json.load(urllib.request.urlopen(base+'/review.json'))
                self.assertEqual(data['profile_id'], 'owner')
                self.assertEqual(data['items'][0]['feedback'], 'want')
                self.assertEqual(data['items'][0]['my_rating'], 7)
                self.assertEqual(data['items'][0]['predicted_rating'], 7.12)
                self.assertEqual(data['items'][0]['prediction_stage'], 'preliminary')
                self.assertEqual(len(data['items'][0]['reasons']['positive_features']), 1)
                pref = urllib.request.Request(base+'/track-preferences.json', data=json.dumps({
                    'series_key':'kp:tv:123','kind':'audio','profile_id':'other',
                    'descriptor':{'lang':'ru','title':'lostfilm'}
                }).encode(), headers={'Content-Type':'application/json'})
                self.assertTrue(json.load(urllib.request.urlopen(pref))['ok'])
                saved = json.load(urllib.request.urlopen(base+'/track-preferences.json?series_key=kp:tv:123'))
                self.assertEqual(saved['preferences']['audio']['title'], 'lostfilm')
                check = self.connect()
                self.assertEqual(check.execute('SELECT profile_id FROM track_preferences').fetchone()[0], 'owner')
                check.close()
                bad = urllib.request.Request(base+'/review-feedback.json', data=b'{"kp_id":42,"status":"bad"}')
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(bad)
                self.assertEqual(error.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()
                worker.join()


if __name__ == '__main__':
    unittest.main()

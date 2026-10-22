import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import profiles
import kp_sync


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'test.sqlite3'
        c=self.connect()
        c.executescript((Path(__file__).parent/'schema.sql').read_text())
        profiles.ensure(c,'owner','Основной')
        self.other=profiles.create(c,{'name':'Второй'})['id']
        c.execute("INSERT INTO media(kp_id,media_type,title,metadata_status) VALUES(42,'tv','Test','ready')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',42,8)")
        c.commit();c.close()

    def connect(self):
        c=sqlite3.connect(self.path,timeout=5)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def tearDown(self):
        self.temp.cleanup()

    def save(self,c,profile,values,base=None,seed=False,device='pc'):
        return profiles.save_state(c,profile,{'values':values,'base':base or {},'seed':seed,'device_id':device})

    def test_owner_is_unchanged_and_new_profile_is_empty(self):
        c=self.connect();profiles.ensure(c,'owner','Do not rename')
        data=profiles.listing(c,'owner')
        self.assertEqual(next(p for p in data['profiles'] if p['owner'])['lampac_profile_id'],'')
        self.assertEqual(c.execute("SELECT rating FROM user_ratings WHERE profile_id='owner'").fetchone()[0],8)
        self.assertEqual(profiles.catalog_data(c,self.other)['ratings'],[])
        self.assertEqual(profiles.state(c,self.other)['values'],{})
        c.close()

    def test_watchlist_unions_wants_excludes_ratings_seen_and_other_profiles(self):
        from review_api import ensure_schema, save_feedback
        c=self.connect();ensure_schema(c)
        for kp in range(43,48):
            c.execute("INSERT INTO media(kp_id,media_type,title,metadata_status) VALUES(?,'movie','Watch','ready')",(kp,))
        for kp in (42,43,44):
            c.execute("INSERT INTO watchlist(profile_id,kp_id,source) VALUES('owner',?,'kinopoisk')",(kp,))
        c.commit()
        save_feedback(c,'owner',{'kp_id':44,'status':'seen'})
        save_feedback(c,'owner',{'kp_id':45,'status':'want'})
        save_feedback(c,'owner',{'kp_id':43,'status':'want'})
        save_feedback(c,self.other,{'kp_id':46,'status':'want'})
        self.assertEqual([r['kp_id'] for r in profiles.catalog_data(c,'owner')['watchlist']],[43,45])
        self.assertEqual([r['kp_id'] for r in profiles.catalog_data(c,self.other)['watchlist']],[46])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM watchlist WHERE profile_id='owner'").fetchone()[0],3)
        c.close()

    def test_state_isolated_and_first_snapshot_is_backed_up(self):
        c=self.connect()
        first={'homecinema_appearance':'apple','file_view':{'a':{'percent':100,'updated':10}}}
        self.save(c,'owner',first,seed=True)
        self.save(c,self.other,{'homecinema_appearance':'original'},seed=True)
        self.assertEqual(profiles.state(c,'owner')['values'],first)
        self.save(c,'owner',{'homecinema_appearance':'original'},base=first)
        self.assertEqual(json.loads(c.execute("SELECT document FROM home_profile_backups WHERE profile_id='owner'").fetchone()[0]),first)
        c.close()

    def test_machine_credentials_are_rejected(self):
        c=self.connect()
        for key in ('plugins','torrserver_password','torrserver_url','jackett_key','account'):
            with self.assertRaises(ValueError):self.save(c,'owner',{key:'secret'},seed=True)
        self.assertEqual(profiles.state(c,'owner')['revision'],0)
        c.close()

    def test_old_device_seed_does_not_overwrite_new_progress_or_theme(self):
        c=self.connect()
        self.save(c,'owner',{'file_view':{'a':{'updated':20,'percent':100}},'homecinema_appearance':'apple',
            'online_watched_last':{'show':{'season':2,'episode':2}}},seed=True)
        self.save(c,'owner',{'file_view':{'a':{'updated':10,'percent':20},'b':{'updated':15}},
            'homecinema_appearance':'original','online_watched_last':{'show':{'season':1,'episode':6}}},seed=True,device='tv')
        state=profiles.state(c,'owner')['values']
        self.assertEqual(state['file_view']['a']['percent'],100)
        self.assertIn('b',state['file_view'])
        self.assertEqual(state['online_watched_last']['show']['season'],2)
        self.assertEqual(state['homecinema_appearance'],'apple')
        c.close()

    def test_old_device_seeds_filters_without_merging_seasons_or_treating_arrays_as_progress(self):
        c=self.connect()
        remote={'torrents_filter_data':{'1:tv':{'season':['2'],'homecinema_scoped_season':True}}}
        self.save(c,'owner',remote,seed=True)
        self.save(c,'owner',{'torrents_filter_data':{'1:tv':{'season':['1']},'2:tv':{'season':['3']}}},seed=True,device='oldtv')
        filters=profiles.state(c,'owner')['values']['torrents_filter_data']
        self.assertEqual(filters['1:tv'],remote['torrents_filter_data']['1:tv'])
        self.assertEqual(filters['2:tv']['season'],['3'])
        c.close()

    def test_concurrent_changes_merge_per_item_but_settings_conflict(self):
        c=self.connect()
        initial={'file_view':{},'homecinema_appearance':'apple'}
        self.save(c,'owner',initial,seed=True)
        self.save(c,'owner',{'file_view':{'a':{'updated':1}},'homecinema_appearance':'original'},base=initial)
        self.save(c,'owner',{'file_view':{'b':{'updated':2}}},base=initial,device='tv')
        self.assertEqual(set(profiles.state(c,'owner')['values']['file_view']),{'a','b'})
        with self.assertRaises(profiles.Conflict):
            self.save(c,'owner',{'homecinema_appearance':'another'},base=initial,device='tv')
        self.assertEqual(profiles.state(c,'owner')['values']['homecinema_appearance'],'original')
        c.close()

    def test_stale_timeline_does_not_regress_even_without_a_concurrent_request(self):
        c=self.connect()
        first={'file_view':{'a':{'updated':20,'percent':100}}}
        self.save(c,'owner',first,seed=True)
        self.save(c,'owner',{'file_view':{'a':{'updated':10,'percent':10}}},base=first)
        self.assertEqual(profiles.state(c,'owner')['values']['file_view']['a']['percent'],100)
        c.close()

    def test_legacy_partial_snapshot_keeps_other_timeline_records(self):
        c=self.connect()
        first={'file_view':{'a':{'updated':20},'b':{'updated':30}},
               'online_watched_last':{'a':{'season':2,'episode':2,'_hc_updated':30},'b':{'season':1,'episode':3}}}
        self.save(c,'owner',first,seed=True)
        self.save(c,'owner',{'file_view':{'a':{'updated':10}},'online_watched_last':{'a':{'season':1,'episode':5}}},base=first)
        state=profiles.state(c,'owner')['values']
        self.assertIn('b',state['file_view']);self.assertIn('b',state['online_watched_last'])
        self.assertEqual(state['online_watched_last']['a']['season'],2)
        c.close()

    def test_notifications_are_scoped_and_hidden_series_are_excluded(self):
        from datetime import date
        import review_api
        c=self.connect();review_api.ensure_schema(c)
        c.execute('CREATE TABLE episode_schedules(kp_id PRIMARY KEY,episodes_json)')
        episodes=[{'season':2,'episode':3,'date':date.today().isoformat()}]
        c.execute('INSERT INTO episode_schedules VALUES(?,?)',(42,json.dumps(episodes)));c.commit()
        self.assertEqual(len(profiles.notices(c,'owner')['items']),1)
        self.assertEqual(profiles.notices(c,self.other)['items'],[])
        review_api.save_feedback(c,'owner',{'kp_id':42,'status':'not_interested'})
        self.assertEqual(profiles.notices(c,'owner')['items'],[]);c.close()

    def test_removal_does_not_reappear_from_stale_list(self):
        c=self.connect();original={'favorite':{'card':[{'id':1},{'id':2}],'history':[1,2]}}
        self.save(c,'owner',original,seed=True)
        self.save(c,'owner',{'favorite':{'card':[{'id':2}],'history':[2]}},base=original)
        changed=copy.deepcopy(original);changed['favorite']['history'].append(3);changed['favorite']['card'].append({'id':3})
        self.save(c,'owner',changed,base=original,device='tv')
        result=profiles.state(c,'owner')['values']['favorite']
        self.assertEqual(result['history'],[2,3]);self.assertEqual([r['id'] for r in result['card']],[2,3]);c.close()

    def test_http_profiles_and_scoped_personal_endpoints(self):
        import review_api
        c=self.connect();review_api.ensure_schema(c);c.close()
        with patch.object(kp_sync,'direct_connection',self.connect),patch.object(kp_sync,'PROFILE_ID','owner'):
            server=ThreadingHTTPServer(('127.0.0.1',0),kp_sync.Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            root='http://127.0.0.1:'+str(server.server_port)
            def call(path,payload=None):
                request=Request(root+path,data=json.dumps(payload).encode() if payload is not None else None,
                                headers={'Content-Type':'application/json'})
                return json.load(urlopen(request))
            try:
                self.assertEqual(call('/profiles.json')['owner_id'],'owner')
                state=call('/profile-state.json',{'profile_id':self.other,'device_id':'pc','seed':True,'values':{'homecinema_appearance':'apple'}})
                self.assertEqual(state['profile_id'],self.other)
                self.assertEqual(call('/p/'+self.other+'/data.json')['ratings'],[])
                self.assertIsNone(call('/p/'+self.other+'/card-ratings.json?kp_id=42&cached=1')['my_rating'])
                self.assertEqual(call('/p/owner/card-ratings.json?kp_id=42&cached=1')['my_rating'],8)
                call('/p/'+self.other+'/review-feedback.json',{'kp_id':42,'status':'not_interested'})
                call('/p/'+self.other+'/track-preferences.json',{'series_key':'kp:tv:42','kind':'audio','descriptor':{'lang':'ru'}})
                c=self.connect()
                self.assertEqual(c.execute('SELECT profile_id FROM recommendation_feedback').fetchone()[0],self.other)
                self.assertEqual(c.execute('SELECT profile_id FROM track_preferences').fetchone()[0],self.other)
                self.assertEqual(c.execute('SELECT profile_id FROM user_ratings').fetchone()[0],'owner');c.close()
                with self.assertRaises(HTTPError) as error:call('/p/unknown/data.json')
                self.assertEqual(error.exception.code,404)
            finally:
                server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()

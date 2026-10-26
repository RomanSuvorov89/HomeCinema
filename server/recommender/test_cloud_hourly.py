"""Two real SQLite servers and deterministic Disk transport; no real Yandex calls."""
import copy
import json
import sqlite3
import time
from unittest.mock import patch
import unittest
from pathlib import Path
import cloud_disk as cloud
import profiles
import connections
import test_cloud_disk as fixtures


class HourlyTest(unittest.TestCase):
    setUp = fixtures.CloudTest.setUp
    tearDown = fixtures.CloudTest.tearDown
    factory = fixtures.CloudTest.factory

    def start(self):
        self.m.config.update(access_token='TOKEN',expires=10**12,instance='a'*32)
        self.m.enable_auto()
        self.m.save(True)

    def second(self):
        db=self.root/'second.sqlite3'
        def factory():
            c=sqlite3.connect(db,timeout=5);c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON');return c
        c=factory();c.executescript((Path(__file__).parent/'schema.sql').read_text())
        profiles.ensure(c,'new_owner','New home');connections.ensure(c);c.close()
        other=cloud.Manager(self.root/'second-cloud',factory,'new_owner',self.disk)
        other.config.update(access_token='TOKEN',expires=10**12,instance='b'*32)
        preview=other.preview(self.m.versions()['items'][0]['name'])
        other.apply(preview['ticket'])
        return other,factory

    def versions(self):
        return [name for name in self.disk.files if name.endswith('.hcb')]

    def change(self,factory,owner,device,base,values):
        c=factory()
        profiles.save_state(c,owner,{'device_id':device,'base':base,'values':values,'generation':profiles.generation(c)})
        c.close()

    def state(self,factory,owner):
        c=factory();value=profiles.state(c,owner)['values'];c.close();return value

    def test_hourly_noop_persistent_comparison_and_volatile_changes(self):
        self.start();count=len(self.versions());requests=len(self.disk.requests)
        self.m.save()
        self.assertEqual(len(self.disk.requests),requests,'no Disk access before one hour')
        c=self.factory()
        c.execute('UPDATE profiles SET updated_at=updated_at+10')
        c.execute('UPDATE media SET kp_vote_count=12345')
        c.execute('UPDATE home_profile_state SET revision=revision+100,updated_at=updated_at+100')
        c.commit();c.close()
        restarted=cloud.Manager(self.root/'cloud',self.factory,'owner',self.disk)
        with patch.object(cloud.time,'time',return_value=restarted.config['last_check']+3601):
            restarted.save()
        self.assertGreater(len(self.disk.requests),requests,'hourly cycle reads cloud even without local changes')
        self.assertEqual(len(self.versions()),count,'poll revisions and metadata are not user changes')
        restarted.save(True)
        self.assertEqual(len(self.versions()),count,'manual sync also skips identical state')

    def test_pc_and_tv_within_hour_are_merged_before_cloud_upload(self):
        self.start();base=self.state(self.factory,'owner')
        self.change(self.factory,'owner','pc',base,{'file_view':{**base['file_view'],'movie_pc':{'updated':1000,'percent':100}}})
        self.change(self.factory,'owner','tv',base,{'file_view':{**base['file_view'],'episode_tv':{'updated':2000,'percent':75}}})
        self.m.save(True)
        other,factory=self.second()
        state=self.state(factory,'new_owner')
        self.assertEqual(state['file_view']['movie_pc']['percent'],100)
        self.assertEqual(state['file_view']['episode_tv']['percent'],75)
        self.assertEqual(state['file_view']['episode']['percent'],100)
        count=len(self.versions());other.save(True)
        self.assertEqual(len(self.versions()),count,'restore/pull does not echo the same snapshot back')

    def test_simultaneous_servers_converge_without_overwriting_each_other(self):
        self.start();other,factory=self.second()
        initial=self.m.versions()
        a=self.state(self.factory,'owner');b=self.state(factory,'new_owner')
        self.change(self.factory,'owner','pc',a,{'file_view':{**a['file_view'],'film_a':{'updated':3000,'percent':100}}})
        self.change(factory,'new_owner','tv',b,{'file_view':{**b['file_view'],'film_b':{'updated':4000,'percent':80}}})
        # Both have read the same old listing before either independent upload.
        with patch.object(self.m,'versions',return_value=initial):self.m.save(True)
        with patch.object(other,'versions',return_value=initial):other.save(True)
        self.m.save(True);other.save(True)
        for f,owner in ((self.factory,'owner'),(factory,'new_owner')):
            state=self.state(f,owner)
            self.assertEqual(state['file_view']['film_a']['percent'],100)
            self.assertEqual(state['file_view']['film_b']['percent'],80)
        count=len(self.versions())
        self.m.save(True);other.save(True)
        self.assertEqual(len(self.versions()),count,'converged servers do not generate a copy loop')

    def test_deletions_do_not_return_and_pc_tv_device_settings_stay_separate(self):
        self.start();other,factory=self.second()
        a=self.state(self.factory,'owner')
        self.change(self.factory,'owner','pc',a,{'search_history':['remove me']})
        self.m.devices={'pc':{'values':{'player_volume':30},'updated_at':1},'tv':{'values':{'player_volume':90},'updated_at':2}}
        self.m.save(True);other.save(True)
        a=self.state(self.factory,'owner')
        self.change(self.factory,'owner','pc',a,{'search_history':[]})
        self.m.save(True);other.save(True)
        self.assertEqual(self.state(factory,'new_owner')['search_history'],[])
        other.devices['tv']['values']['player_volume']=75
        other.save(True);self.m.save(True)
        self.assertEqual(self.m.devices['pc']['values']['player_volume'],30)
        self.assertEqual(self.m.devices['tv']['values']['player_volume'],75)
        self.assertEqual(self.state(self.factory,'owner')['search_history'],[])

    def test_same_episode_uses_view_clock_and_favorite_removals_survive_stale_server(self):
        self.start();other,factory=self.second()
        initial=self.m.versions()
        a=self.state(self.factory,'owner');b=self.state(factory,'new_owner')
        # Lower percent can be a later rewatch; the episode's own clock wins.
        self.change(self.factory,'owner','pc',a,{'file_view':{**a['file_view'],'same':{'updated':5000,'percent':100}},
            'favorite':{'card':[{'id':10,'title':'Ten'}],'wath':[10]}})
        self.change(factory,'new_owner','tv',b,{'file_view':{**b['file_view'],'same':{'updated':6000,'percent':20}},
            'favorite':{'card':[{'id':20,'title':'Twenty'}],'wath':[20]}})
        with patch.object(self.m,'versions',return_value=initial):self.m.save(True)
        with patch.object(other,'versions',return_value=initial):other.save(True)
        self.m.save(True);other.save(True)
        for f,owner in ((self.factory,'owner'),(factory,'new_owner')):
            state=self.state(f,owner)
            self.assertEqual(state['file_view']['same']['percent'],20)
            self.assertEqual(set(state['favorite']['wath']),{10,20})
        a=self.state(self.factory,'owner')
        favorite=copy.deepcopy(a['favorite']);favorite['wath'].remove(10)
        self.change(self.factory,'owner','pc',a,{'favorite':favorite})
        self.m.save(True)
        # The other server changes an unrelated field while still carrying item 10.
        b=self.state(factory,'new_owner')
        self.change(factory,'new_owner','tv',b,{'language':'en'})
        other.save(True);self.m.save(True)
        self.assertEqual(self.state(factory,'new_owner')['favorite']['wath'],[20])
        self.assertEqual(self.state(self.factory,'owner')['language'],'en')

    def test_ratings_watchlist_and_connections_merge_without_catalog_refresh_noise(self):
        self.start();other,factory=self.second()
        c=self.factory()
        c.execute("INSERT INTO media(kp_id,media_type,title) VALUES(99,'movie','New Film')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',99,9)")
        c.execute("INSERT INTO watchlist(profile_id,kp_id) VALUES('owner',42)")
        c.commit();c.close()
        self.m.save(True);other.save(True)
        c=factory()
        self.assertEqual(c.execute("SELECT rating FROM user_ratings WHERE profile_id='new_owner' AND kp_id=99").fetchone()[0],9)
        self.assertEqual(c.execute("SELECT title FROM media WHERE kp_id=99").fetchone()[0],'New Film')
        c.execute("DELETE FROM watchlist WHERE profile_id='new_owner' AND kp_id=42")
        c.execute("UPDATE home_connections SET kp_id='654321' WHERE profile_id='new_owner'")
        c.commit();c.close()
        other.save(True);self.m.save(True)
        c=self.factory()
        self.assertEqual(c.execute('SELECT COUNT(*) FROM watchlist').fetchone()[0],0)
        self.assertEqual(c.execute("SELECT kp_id FROM home_connections WHERE profile_id='owner'").fetchone()[0],'654321')
        c.close()

    def test_favorite_order_and_native_empty_categories_do_not_create_versions(self):
        self.start();a=self.state(self.factory,'owner')
        self.change(self.factory,'owner','pc',a,{'favorite':{'card':[{'id':20},{'id':10}],'wath':[20,10]}})
        self.m.save(True);other,factory=self.second()
        self.assertEqual(self.state(factory,'new_owner')['favorite']['wath'],[20,10])
        count=len(self.versions())
        a=self.state(self.factory,'owner');favorite=copy.deepcopy(a['favorite'])
        favorite.update(viewed=[],scheduled=[],book=[])
        self.change(self.factory,'owner','pc',a,{'favorite':favorite})
        self.m.save(True)
        self.assertEqual(len(self.versions()),count,'native initialization is not a personal change')

    def test_removing_last_favorite_does_not_drop_a_concurrent_new_item(self):
        self.start();a=self.state(self.factory,'owner')
        self.change(self.factory,'owner','pc',a,{'favorite':{'card':[{'id':10}],'wath':[10]}})
        self.m.save(True);other,factory=self.second();initial=self.m.versions()
        a=self.state(self.factory,'owner');b=self.state(factory,'new_owner')
        self.change(self.factory,'owner','pc',a,{'favorite':{'card':[{'id':10}],'wath':[]}})
        favorite=copy.deepcopy(b['favorite']);favorite['wath'].append(20);favorite['card'].append({'id':20})
        self.change(factory,'new_owner','tv',b,{'favorite':favorite})
        with patch.object(self.m,'versions',return_value=initial):self.m.save(True)
        with patch.object(other,'versions',return_value=initial):other.save(True)
        self.m.save(True);other.save(True)
        self.assertEqual(self.state(factory,'new_owner')['favorite']['wath'],[20])
        self.assertEqual(self.state(self.factory,'owner')['favorite']['wath'],[20])

    def test_upgrade_existing_copy_and_restart_does_not_upload_unchanged_settings(self):
        self.start()
        name=self.m.versions()['items'][0]['name']
        document=self.m.sync_document(name);document.pop('cloud_sync')
        self.disk.files[name]=cloud.encrypt(document,cloud.base64.b64decode(self.m.config['key']),
            cloud.base64.b64decode(self.m.config['salt']),cloud.AUTO_MAGIC)
        cloud.private_write(self.root/'cloud/hourly-sync.json',b'{}')
        upgraded=cloud.Manager(self.root/'cloud',self.factory,'owner',self.disk)
        upgraded.save(True)
        self.assertEqual(len(self.versions()),1,'migration reads the existing snapshot without making a duplicate')
        restarted=cloud.Manager(self.root/'cloud',self.factory,'owner',self.disk)
        restarted.save(True)
        self.assertEqual(len(self.versions()),1)
        a=self.state(self.factory,'owner')
        self.change(self.factory,'owner','pc',a,{'language':'en'})
        restarted.save(True)
        self.assertEqual(len(self.versions()),2,'a genuine personal change publishes a new version')
        latest=restarted.sync_document(restarted.versions()['items'][0]['name'])
        self.assertEqual(latest['cloud_sync']['version'],1)

    def test_pending_server_write_during_download_is_included(self):
        self.start();other,factory=self.second()
        b=self.state(factory,'new_owner')
        self.change(factory,'new_owner','tv',b,{'search_history':['from other server']})
        other.save(True)
        real=self.m.sync_document;changed=False
        def fetch(name):
            nonlocal changed
            result=real(name)
            if not changed:
                changed=True;a=self.state(self.factory,'owner')
                self.change(self.factory,'owner','pc',a,{'file_view':{**a['file_view'],'during_download':{'updated':9000,'percent':55}}})
            return result
        with patch.object(self.m,'sync_document',side_effect=fetch):self.m.save(True)
        state=self.state(self.factory,'owner')
        self.assertEqual(state['file_view']['during_download']['percent'],55)
        self.assertEqual(state['search_history'],['from other server'])

if __name__=='__main__':unittest.main()

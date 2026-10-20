import json
import tempfile
import time
import unittest
from pathlib import Path
from home_cache import Cache, Builder

class HomeCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cache=Cache(Path(self.tmp.name)/'cache.db')
        self.calls=[]
        self.offline=False
    def tearDown(self): self.tmp.cleanup()
    def fetch(self, route):
        self.calls.append(route)
        if self.offline: raise RuntimeError('offline')
        return {'results':[{'id':10,'title':'Movie','release_date':'2026-01-01'}]}
    def personal(self):
        return [{'kp_id':1,'title':'Movie','release_year':2026,'media_type':'movie','final_score':80}], []
    def test_server_cache_survives_restart_and_get_never_fetches(self):
        b=Builder(self.cache,'roman',self.fetch,self.personal);b.refresh()
        cold=len(self.calls)
        snap=Cache(self.cache.path).snapshot('roman')
        self.assertEqual(len(self.calls),cold)
        self.assertEqual(next(r for r in snap['rows'] if r['kind']=='ai')['results'][0]['kinopoisk_id'],'1')
        self.assertEqual(len(snap['rows']),6)
        b.refresh()
        self.assertEqual(len(self.calls),cold+2,'only shared rows; identity lookup cached')
    def test_offline_preserves_last_good_rows(self):
        b=Builder(self.cache,'roman',self.fetch,self.personal);b.refresh()
        original=self.cache.snapshot('roman')['rows']
        self.offline=True;b.refresh()
        now=self.cache.snapshot('roman')['rows']
        self.assertEqual([(r['kind'],[c['id'] for c in r['results']]) for r in now],
                         [(r['kind'],[c['id'] for c in r['results']]) for r in original])
        self.assertTrue(b.warming,'failed CUB refresh must retry without waiting 15 minutes')
    def test_no_profile_and_isolation(self):
        b=Builder(self.cache,'roman',self.fetch,self.personal);b.refresh()
        other=self.cache.snapshot('other')
        self.assertEqual({r['kind'] for r in other['rows']},{'fire','now'})
        Builder(self.cache,'no-kp',self.fetch,lambda:([],[])).refresh()
        snap=self.cache.snapshot('no-kp')
        self.assertTrue(next(r for r in snap['rows'] if r['kind']=='ai')['results']==[])
    def test_failed_new_mapping_keeps_complete_shelf(self):
        b=Builder(self.cache,'roman',self.fetch,self.personal);b.refresh()
        old=next(r for r in self.cache.snapshot('roman')['rows'] if r['kind']=='ai')
        self.offline=True
        b.group('ai',[{'kp_id':2,'title':'Another','release_year':2026,'media_type':'movie'}])
        self.assertEqual(next(r for r in self.cache.snapshot('roman')['rows'] if r['kind']=='ai'),old)
    def test_negative_results_have_retry_deadline(self):
        item={'kp_id':9,'title':'Absent','media_type':'tv'}
        self.cache.mapping(item,None)
        self.assertEqual(self.cache.mapped(item),(True,None))
        with self.cache.connect() as c:c.execute('UPDATE identity_links SET checked_at=0')
        self.assertEqual(self.cache.mapped(item),(False,None))

    def test_full_review_snapshot_revision_and_offline_read(self):
        Builder(self.cache,'roman',self.fetch,self.personal).refresh()
        report=self.cache.review_snapshot('roman')
        self.assertEqual(report['items'][0]['card']['id'],10)
        self.assertEqual(self.cache.review_snapshot('roman',report['revision']),
                         {'revision':report['revision'],'unchanged':True})
        self.assertEqual(self.cache.review_snapshot('other')['items'],[])
        calls=len(self.calls)
        self.assertEqual(Cache(self.cache.path).review_snapshot('roman'),report)
        self.assertEqual(len(self.calls),calls)

    def test_shared_card_does_not_leak_profile_features(self):
        card={'id':10,'source':'cub','media_type':'movie','kinopoisk_id':'1','roman_review':{'my_rating':9}}
        self.cache.publish('roman','ai',[(card,{'my_rating':9})])
        self.cache.publish('*','fire',[({'id':10,'source':'cub','media_type':'movie'}, {})])
        other=self.cache.snapshot('other')['rows'][0]['results'][0]
        self.assertNotIn('roman_review',other)
        self.assertEqual(other['kinopoisk_id'],'1')

    def test_shared_shelves_filter_watched_and_archive_without_profile_leak(self):
        cards=[{'id':1,'kinopoisk_id':'100','title':'Seen TV','media_type':'tv','first_air_date':'2011-01-01'},
               {'id':2,'kinopoisk_id':'101','title':'Old movie','release_date':'2002-01-01'},
               {'id':3,'kinopoisk_id':'102','title':'New movie','release_date':'2026-01-01'},
               {'id':4,'kinopoisk_id':'103','title':'Camera','release_date':'2026-01-01','release_quality':'TS'}]
        def fetch(route): return {'results':cards} if not route.startswith('search/') else {'results':[]}
        personal=lambda:([],[],[],False,{'rated':[100],'seen':[]})
        Builder(self.cache,'roman',fetch,personal).refresh()
        own=self.cache.snapshot('roman')['rows']
        self.assertEqual([r['id'] for row in own if row['kind']=='fire' for r in row['results']],[1,3])
        self.assertEqual(len([r for r in own if r['kind']=='fire']),1)
        other=self.cache.snapshot('other')['rows']
        self.assertEqual(len(next(r for r in other if r['kind']=='fire')['results']),4)

    def test_offline_migration_cleans_old_feed_and_keeps_rated_new_fire(self):
        cards=[{'id':1,'kinopoisk_id':'328','media_type':'movie','release_date':'2001-12-18'},
               {'id':2,'kinopoisk_id':'5098653','title':'Ущелье','media_type':'movie','release_date':'2025-02-13'},
               {'id':3,'kinopoisk_id':'1178445','name':'Эйфория','media_type':'tv','first_air_date':'2019-06-16'},
               {'id':4,'kinopoisk_id':'585595','media_type':'tv','first_air_date':'2011-10-23'}]
        for kind in ('fire','now'):self.cache.publish('*',kind,[(c,{}) for c in cards])
        def unavailable(route):raise RuntimeError('connection refused')
        context={'rated':[328,5098653],'seen':[],'ended':[585595],
                 'card_predictions':{'1178445':{'kp_id':1178445,'predicted_rating':6.5}}}
        builder=Builder(self.cache,'roman',unavailable,lambda:([],[],[],False,context))
        builder.refresh()
        rows={r['kind']:r['results'] for r in self.cache.snapshot('roman')['rows']}
        self.assertEqual(rows['fire'][0]['title'],'Ущелье')
        self.assertEqual([c['id'] for c in rows['now']],[3])
        self.assertTrue(builder.warming)
        self.assertEqual(len(self.cache.snapshot('other')['rows'][0]['results']),4)

    def test_personal_now_requires_real_prediction(self):
        cards=[{'id':1,'kinopoisk_id':'585595','name':'Unknown show','media_type':'tv'},
               {'id':2,'kinopoisk_id':'1178445','name':'Эйфория','media_type':'tv'}]
        for kind in ('fire','now'):self.cache.publish('*',kind,[(c,{}) for c in cards])
        context={'rated':[],'card_predictions':{'1178445':{'kp_id':1178445,'predicted_rating':6.5}}}
        def offline(route):raise RuntimeError('offline')
        Builder(self.cache,'roman',offline,lambda:([],[],[],False,context)).refresh()
        now=next(r for r in self.cache.snapshot('roman')['rows'] if r['kind']=='now')
        self.assertEqual([c['id'] for c in now['results']],[2])
        self.assertEqual(now['results'][0]['roman_review']['predicted_rating'],6.5)

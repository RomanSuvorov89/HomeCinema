import unittest
from pathlib import Path
from datetime import date
import test_candidate_engine
from episode_schedule import parse_episodes,refresh
from kp_sync import series_state,save_series_tracking,rated_airing_series

class ScheduleTest(unittest.TestCase):
    def test_real_schedule_and_persistent_refresh(self):
        html=Path('tests/fixtures/kinopoisk-5024113-episodes.html').read_text()
        episodes=parse_episodes(html)
        self.assertEqual(len(episodes),19)
        state=lambda m:series_state(m,date(2026,10,1))
        self.assertEqual(state({'episodes':episodes})['next_air_date'],'2026-10-02')
        c=test_candidate_engine.CandidateEngineTests().connection()
        c.execute("INSERT INTO media(kp_id,title,media_type) VALUES(5024113,'Тёмная материя','movie')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',5024113,8)")
        calls=[]
        def fetch(url):calls.append(url);return html
        refresh(c,fetch,state,save_series_tracking,'owner',[5024113])
        self.assertEqual(len(rated_airing_series(c,'owner',date(2026,10,1))),1)
        refresh(c,fetch,state,save_series_tracking,'owner')
        self.assertEqual(len(calls),1,'six-hour cache must avoid refetching')
        c.execute('UPDATE episode_schedules SET checked_at=0,attempted_at=0')
        refresh(c,lambda url:'<body>SSO challenge</body>',state,save_series_tracking,'owner')
        # Invalid response preserves the last usable schedule and marks an error.
        self.assertIn('No dated',c.execute('SELECT error FROM episode_schedules').fetchone()[0])
        self.assertEqual(len(rated_airing_series(c,'owner',date(2026,10,1))),1)
        c.close()

    def test_future_season_does_not_activate_watched_show(self):
        episodes=[{'season':1,'episode':1,'date':'2024-01-01'},
                  {'season':1,'episode':8,'date':'2024-02-20'},
                  {'season':2,'episode':1,'date':'2026-11-11'},
                  {'season':2,'episode':2,'date':'2026-11-18'}]
        state=series_state({'episodes':episodes,'status':'ongoing'},date(2026,10,2))
        self.assertNotEqual(state['airing_state'],'airing')
        self.assertIsNone(state['active_from'])
        premiere=series_state({'episodes':episodes,'status':'ongoing'},date(2026,11,11))
        self.assertEqual(premiere['airing_state'],'airing')
        self.assertEqual(premiere['active_from'],'2026-11-11')
        self.assertEqual(premiere['current_season'],2)

    def test_future_first_season_and_unsorted_dates(self):
        episodes=[{'season':1,'episode':2,'date':'2026-10-09'},
                  {'season':1,'episode':1,'date':'2026-10-02'}]
        self.assertNotEqual(series_state({'episodes':episodes},date(2026,10,1))['airing_state'],'airing')
        self.assertEqual(series_state({'episodes':episodes},date(2026,10,2))['active_from'],'2026-10-02')

    def test_series_vote_can_use_film_url(self):
        from kp_sync import VotesParser
        parser=VotesParser()
        parser.feed('<div class="item"><div class="nameRus"><a href="/film/5024113/">Тёмная материя (сериал, 2024)</a></div><div class="vote">8</div></div>')
        self.assertEqual(parser.rows[0]['media_type'],'tv')
        self.assertEqual(parser.rows[0]['title'],'Тёмная материя')

    def test_scripts_and_impossible_dates_are_not_schedules(self):
        self.assertEqual(parse_episodes('<script>Сезон 1 Эпизод 1 2 октября 2026</script>'),[])
        self.assertEqual(parse_episodes('<h2>Сезон 1</h2>Эпизод 1 31 февраля 2026'),[])
        self.assertEqual(parse_episodes('Рекомендации: 2 октября 2026'),[])


class PartialScheduleTest(unittest.TestCase):
    html='Сезон 1 Эпизод 1 5 августа 2020 Эпизод 2 12 августа 2020 Сезон 2 Эпизод 1 2026 Эпизод 2 2026'
    known=[{'season':1,'episode':1,'date':'2020-08-05'}, {'season':1,'episode':2,'date':'2020-08-12'}]
    fresh=[{'season':1,'number':1,'airdate':'2020-08-05'}, {'season':1,'number':2,'airdate':'2020-08-12'},
           {'season':2,'number':1,'airdate':'2026-09-30'}, {'season':2,'number':2,'airdate':'2026-10-07'}]
    media={'imdb_id':None,'original_title':'Test Show','release_year':2020}

    def api(self,url):
        if '/search/shows?' in url:
            return [{'show':{'id':50,'name':'Test Show','premiered':'2020-08-05'}}]
        return self.fresh

    def test_missing_imdb_requires_name_year_and_known_dates(self):
        from episode_schedule import fallback_episodes
        result=fallback_episodes(self.media,self.known,self.api)
        self.assertEqual(result[-1]['date'],'2026-10-07')
        wrong=[dict(e,date='2021-01-01') for e in self.known]
        with self.assertRaisesRegex(ValueError,'known episode dates'):
            fallback_episodes(self.media,wrong,self.api)
        def ambiguous(url):return [{'show':{'id':i,'name':'Test Show','premiered':'2020-08-05'}} for i in (50,51)]
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            fallback_episodes(self.media,self.known,ambiguous)

    def test_exact_imdb_is_verified(self):
        from episode_schedule import fallback_episodes
        def api(url):
            if '/lookup/' in url:return {'id':50,'externals':{'imdb':'tt1234567'}}
            return self.fresh
        self.assertEqual(len(fallback_episodes(dict(self.media,imdb_id='tt1234567'),[],api)),4)
        with self.assertRaisesRegex(ValueError,'IMDb mismatch'):
            fallback_episodes(dict(self.media,imdb_id='tt9999999'),[],api)

    def test_partial_schedule_is_detected_and_fills_rated_shelf(self):
        from unittest.mock import patch
        c=test_candidate_engine.CandidateEngineTests().connection()
        c.execute("INSERT INTO media(kp_id,title,original_title,release_year,media_type) VALUES(7,'Тест','Test Show',2020,'tv')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',7,7)")
        state=lambda m:series_state(m,date(2026,10,20))
        with patch('episode_schedule.fetch_json',side_effect=self.api):
            refresh(c,lambda url:self.html,state,save_series_tracking,'owner')
        row=c.execute('SELECT * FROM series_tracking WHERE kp_id=7').fetchone()
        self.assertEqual(row['current_season'],2)
        self.assertEqual(row['last_air_date'],'2026-10-07')
        self.assertEqual(len(rated_airing_series(c,'owner',date(2026,10,20))),1)
        self.assertEqual(c.execute('SELECT error FROM episode_schedules').fetchone()[0],'')
        # An outage must not erase dates already obtained from the fallback.
        c.execute('UPDATE episode_schedules SET checked_at=0,attempted_at=0')
        with patch('episode_schedule.fetch_json',side_effect=OSError('offline')):
            refresh(c,lambda url:self.html,state,save_series_tracking,'owner')
        self.assertIn('Partial schedule',c.execute('SELECT error FROM episode_schedules').fetchone()[0])
        self.assertEqual(c.execute('SELECT last_air_date FROM series_tracking').fetchone()[0],'2026-10-07')
        c.close()

    def test_complete_schedule_does_not_call_fallback(self):
        from unittest.mock import patch
        c=test_candidate_engine.CandidateEngineTests().connection()
        c.execute("INSERT INTO media(kp_id,title,media_type) VALUES(8,'Complete','tv')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',8,7)")
        with patch('episode_schedule.fetch_json') as api:
            refresh(c,lambda url:'Сезон 1 Эпизод 1 7 октября 2026',series_state,save_series_tracking,'owner')
            api.assert_not_called()
        c.close()

    def test_upgrade_refreshes_recent_successful_old_parser_cache(self):
        import time
        c=test_candidate_engine.CandidateEngineTests().connection()
        c.execute("INSERT INTO media(kp_id,title,media_type) VALUES(9,'Upgrade','tv')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',9,7)")
        c.execute("CREATE TABLE episode_schedules(kp_id PRIMARY KEY,episodes_json,checked_at,attempted_at,error)")
        now=int(time.time());c.execute("INSERT INTO episode_schedules VALUES(9,'[]',?,?, '')",(now,now))
        calls=[]
        refresh(c,lambda url:(calls.append(url) or 'Сезон 1 Эпизод 1 7 октября 2026'),series_state,save_series_tracking,'owner')
        self.assertEqual(len(calls),1)
        self.assertEqual(c.execute('SELECT parser_revision FROM episode_schedule_versions').fetchone()[0],2)
        c.close()

if __name__=='__main__':unittest.main()

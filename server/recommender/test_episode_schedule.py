import unittest
from pathlib import Path
from datetime import date
import test_candidate_engine
from episode_schedule import parse_episodes,refresh
from kp_sync import series_state,save_series_tracking,rated_airing_series

class ScheduleTest(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        primary=patch('kinoafisha.load',side_effect=ValueError('No source match in this test'))
        primary.start();self.addCleanup(primary.stop)

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



class PrimaryScheduleTest(unittest.TestCase):
    def test_primary_skips_kinopoisk_and_retains_cached_dates_on_failure(self):
        from unittest.mock import patch,Mock
        c=test_candidate_engine.CandidateEngineTests().connection()
        c.execute("INSERT INTO media(kp_id,title,original_title,release_year,media_type) VALUES(7,'Тест','Test Show',2020,'tv')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',7,7)")
        state=lambda m:series_state(m,date(2026,10,20))
        episodes=[{'season':4,'episode':1,'date':'2026-08-05'}, {'season':4,'episode':10,'date':'2026-10-07'}]
        kp=Mock(side_effect=AssertionError('Kinopoisk must not be called'))
        with patch('kinoafisha.load',return_value=(episodes,'https://www.kinoafisha.info/series/test-show/')):
            refresh(c,kp,state,save_series_tracking,'owner')
        kp.assert_not_called()
        self.assertEqual(len(rated_airing_series(c,'owner',date(2026,10,20))),1)
        self.assertEqual(c.execute('SELECT error FROM episode_schedules').fetchone()[0],'')
        self.assertIn('test-show',c.execute('SELECT url FROM episode_schedule_links').fetchone()[0])
        c.execute('UPDATE episode_schedules SET checked_at=0,attempted_at=0')
        with patch('kinoafisha.load',side_effect=OSError('offline')):
            refresh(c,lambda url:'Сезон 1 Эпизод 1 5 августа 2020 Сезон 4 Эпизод 1 2026',state,save_series_tracking,'owner')
        self.assertIn('Kinopoisk schedule is partial',c.execute('SELECT error FROM episode_schedules').fetchone()[0])
        self.assertEqual(c.execute('SELECT last_air_date FROM series_tracking').fetchone()[0],'2026-10-07')
        c.close()

    def test_new_parser_rechecks_successful_recent_cache(self):
        import time
        from unittest.mock import patch
        c=test_candidate_engine.CandidateEngineTests().connection()
        c.execute("INSERT INTO media(kp_id,title,media_type) VALUES(9,'Upgrade','tv')")
        c.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('owner',9,7)")
        c.execute("CREATE TABLE episode_schedules(kp_id PRIMARY KEY,episodes_json,checked_at,attempted_at,error)")
        now=int(time.time());c.execute("INSERT INTO episode_schedules VALUES(9,'[]',?,?, '')",(now,now))
        with patch('kinoafisha.load',return_value=([{'season':1,'episode':1,'date':'2026-10-07'}],'https://www.kinoafisha.info/series/upgrade/')) as load:
            refresh(c,lambda url:'',series_state,save_series_tracking,'owner')
            self.assertEqual(load.call_count,1)
        self.assertEqual(c.execute('SELECT parser_revision FROM episode_schedule_versions').fetchone()[0],3)
        c.close()

if __name__=='__main__':unittest.main()

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

if __name__=='__main__':unittest.main()

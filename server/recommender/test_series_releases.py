"""Home releases are read-only facts, never fabricated watched positions."""
from datetime import date
import json
from pathlib import Path
import sqlite3
import unittest
import episode_schedule
from review_api import series_releases,home_snapshot


class ReleasesTest(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.c.row_factory=sqlite3.Row
        self.c.executescript(Path('schema.sql').read_text())
        self.c.executescript(episode_schedule.SCHEMA)
        self.c.execute("INSERT INTO media(kp_id,media_type,title,original_title,release_year,tmdb_id) VALUES(42,'tv','Show','Original Show',2024,99)")

    def tearDown(self):self.c.close()

    def put(self,episodes):
        self.c.execute('INSERT OR REPLACE INTO episode_schedules(kp_id,episodes_json) VALUES(42,?)',(json.dumps(episodes),))
        self.c.commit()

    def test_latest_aired_season_excludes_future_and_invalid_dates(self):
        self.put([{'season':1,'episode':12,'date':'2024-03-20'},
                  {'season':2,'episode':8,'date':'2026-10-22'},
                  {'season':3,'episode':1,'date':'2027-01-01'},
                  {'season':2,'episode':9,'date':'2026-10-30'},
                  {'season':5,'episode':1,'date':'not-a-date'}])
        row=series_releases(self.c,date(2026,10,23))[0]
        self.assertEqual((row['season'],row['episode']),(2,8))
        self.assertEqual(row['next_air_date'],'2026-10-30')
        self.assertEqual((row['kp_id'],row['tmdb_id'],row['original_title'],row['release_year']),(42,99,'Original Show',2024))
        later=series_releases(self.c,date(2026,10,30))[0]
        self.assertEqual((later['season'],later['episode']),(2,9))
        self.assertEqual(later['next_air_date'],'2027-01-01')

    def test_unknown_schedule_is_not_treated_as_completed(self):
        for episodes in ([],[{'season':1,'episode':1,'date':'2027-01-01'}],{'unexpected':True}):
            self.put(episodes)
            self.assertEqual(series_releases(self.c,date(2026,10,23)),[])
        self.c.execute("UPDATE episode_schedules SET episodes_json='broken-json'")
        self.assertEqual(series_releases(self.c),[])

    def test_snapshot_reads_schedule_without_writes_or_profile_history(self):
        self.put([{'season':2,'episode':8,'date':'2020-01-01'}])
        self.c.set_authorizer(lambda action,*args: sqlite3.SQLITE_OK if action in (
            sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION) else sqlite3.SQLITE_DENY)
        class Cache:
            def snapshot(self,profile):return {'rows':[{'kind':'continue','results':[{'kinopoisk_id':'42'}]}]}
        snapshot=home_snapshot(self.c,Cache(),'owner')
        self.assertEqual(snapshot['series_releases'][0]['episode'],8)
        self.assertEqual(len(snapshot['rows'][0]['results']),1,'server cannot infer playback from a schedule or rating')
        self.assertNotIn('watched',snapshot['series_releases'][0])

    def test_empty_database_before_first_schedule_refresh(self):
        with sqlite3.connect(':memory:') as c:self.assertEqual(series_releases(c),[])


if __name__=='__main__':unittest.main()

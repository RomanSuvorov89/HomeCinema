import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import kp_sync


SAMPLE_PAGE = r'''<!doctype html><html><head>
<script type="application/ld+json">
{
  "@context":"https://schema.org",
  "@type":"TVSeries",
  "name":"Тест времени",
  "alternativeHeadline":"Time Test",
  "description":"Герой попадает во временную петлю и пытается выжить.",
  "dateCreated":"2024-09-01",
  "duration":"PT1H5M",
  "genre":["фантастика","триллер"],
  "countryOfOrigin":{"@type":"Country","name":"США"},
  "director":[{"@type":"Person","name":"Иван Тестов"}],
  "aggregateRating":{"ratingValue":"7.8","ratingCount":"123 456"}
}
</script>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"film":{"id":123,"status":"FILMING","startYear":2024,"endYear":null,
"ratingImdb":8.1,"imdbId":"tt1234567",
"network":{"name":"Apple TV+"},
"episodes":[
{"seasonNumber":2,"episodeNumber":4,"airDate":"2026-09-15"},
{"seasonNumber":2,"episodeNumber":5,"airDate":"2026-09-28"}
]}}}
</script></head></html>'''


class RecommenderTests(unittest.TestCase):
    def test_kinopoisk_page_parser(self):
        item = kp_sync.parse_kinopoisk_page(SAMPLE_PAGE, 123, "tv")
        self.assertEqual(item["title"], "Тест времени")
        self.assertEqual(item["genres"], ["фантастика", "триллер"])
        self.assertEqual(item["countries"], ["США"])
        self.assertEqual(item["directors"], ["Иван Тестов"])
        self.assertEqual(item["runtime_minutes"], 65)
        self.assertEqual(item["kp_vote_count"], 123456)
        self.assertEqual(item["imdb_rating"], 8.1)
        self.assertEqual(item["imdb_id"], "tt1234567")
        self.assertEqual(item["origin_platform"]["code"], "apple_tv")
        self.assertEqual(item["origin_platform"]["method"], "explicit_network")
        self.assertEqual(len(item["episodes"]), 2)

    def test_related_movie_network_does_not_brand_primary_movie(self):
        page = SAMPLE_PAGE.replace('"network":{"name":"Apple TV+"},', '')
        page += '<script type="application/json">{"related":{"filmId":999,"network":{"name":"NBC"}}}</script>'
        parsed = kp_sync.parse_kinopoisk_page(page, 123, "tv")
        self.assertIsNone(parsed["origin_platform"]["code"])

    def test_themes_are_extracted_locally(self):
        themes = kp_sync.extracted_themes("Герой застрял во временной петле и пытается выжить")
        self.assertIn("путешествия во времени", themes)
        self.assertIn("выживание", themes)

    def test_theatrical_studio_is_not_streaming_platform(self):
        origin = kp_sync.detect_origin_platform(
            [], ["Walt Disney Pictures", "Paramount Pictures"], ["Universal Pictures"], "",
        )
        self.assertIsNone(origin["code"])

    def test_tvmaze_web_channel_is_used_as_original_platform(self):
        origin = kp_sync.origin_from_tvmaze({
            "id": 66748,
            "name": "Silo",
            "network": None,
            "webChannel": {"id": 310, "name": "Apple TV+"},
        })
        self.assertEqual(origin["code"], "apple_tv")
        self.assertEqual(origin["method"], "tvmaze_web_channel")
        self.assertEqual(origin["confidence"], 1.0)

    def test_wikipedia_infobox_fallback_detects_platform(self):
        original = kp_sync.curl_public
        wikitext = """{{Infobox television
| name = Silo
| network = [[Apple TV+]]
| first_aired = 2023
}}
{{IMDb title|tt14688458}}
"""
        try:
            def fake_curl(url):
                if "api.tvmaze.com" in url:
                    raise RuntimeError("blocked")
                if "list=search" in url or "list%3Dsearch" in url:
                    return json.dumps({"query": {"search": [{"title": "Silo (TV series)"}]}})
                return json.dumps({"parse": {"wikitext": wikitext}})

            kp_sync.curl_public = fake_curl
            metadata = {
                "kp_id": 4541515,
                "media_type": "tv",
                "title": "Укрытие",
                "original_title": "Silo",
                "year": 2023,
                "imdb_id": None,
                "origin_platform": {"code": None},
            }
            kp_sync.supplement_origin_platform(metadata)
            self.assertEqual(metadata["origin_platform"]["code"], "apple_tv")
            self.assertEqual(metadata["origin_platform"]["method"], "wikipedia_infobox")
            self.assertEqual(metadata["origin_platform_external"]["page"], "Silo (TV series)")
        finally:
            kp_sync.curl_public = original

    def test_platform_is_persisted_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            old_db = kp_sync.DB_FILE
            try:
                kp_sync.DB_FILE = Path(directory) / "platform.sqlite3"
                connection = kp_sync.open_database()
                connection.execute(
                    "INSERT INTO media(kp_id,media_type,title) VALUES(123,'tv','Тест времени')"
                )
                media = connection.execute("SELECT * FROM media WHERE kp_id=123").fetchone()
                metadata = kp_sync.parse_kinopoisk_page(SAMPLE_PAGE, 123, "tv")
                kp_sync.persist_metadata(connection, media, metadata)
                connection.commit()
                row = connection.execute(
                    "SELECT origin_platform,origin_platform_method,origin_platform_evidence,metadata_revision "
                    "FROM media WHERE kp_id=123"
                ).fetchone()
                network = connection.execute(
                    """SELECT f.external_id FROM media_features mf
                       JOIN features f USING(feature_id)
                       WHERE mf.kp_id=123 AND f.feature_type='network'"""
                ).fetchone()
                connection.close()
                self.assertEqual(row[0], "apple_tv")
                self.assertEqual(row[1], "explicit_network")
                self.assertIn("Apple TV+", row[2])
                self.assertEqual(row[3], kp_sync.METADATA_REVISION)
                self.assertEqual(network[0], "apple_tv")
            finally:
                kp_sync.DB_FILE = old_db

    def test_platform_survives_failed_refresh_and_verified_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            old_db = kp_sync.DB_FILE
            try:
                kp_sync.DB_FILE = Path(directory) / "preserve.sqlite3"
                connection = kp_sync.open_database()
                connection.execute("INSERT INTO media(kp_id,media_type,title) VALUES(123,'tv','Test')")
                media = connection.execute("SELECT * FROM media WHERE kp_id=123").fetchone()
                metadata = kp_sync.parse_kinopoisk_page(SAMPLE_PAGE, 123, "tv")
                kp_sync.persist_metadata(connection, media, metadata)
                metadata["origin_platform"] = {"code": None, "confidence": 0}
                metadata["origin_platform_lookup_error"] = "timeout"
                kp_sync.persist_metadata(connection, media, metadata)  # stale row as in a concurrent worker
                row = connection.execute("SELECT * FROM media WHERE kp_id=123").fetchone()
                self.assertEqual(row["origin_platform"], "apple_tv")
                self.assertIn("Apple TV+", row["origin_platform_evidence"])
                connection.execute("UPDATE media SET origin_platform=NULL,origin_platform_label=NULL,origin_platform_method='verified_correction' WHERE kp_id=123")
                metadata["origin_platform"] = {"code": "nbc", "label": "NBC", "confidence": .95}
                kp_sync.persist_metadata(connection, media, metadata)
                row = connection.execute("SELECT * FROM media WHERE kp_id=123").fetchone()
                self.assertIsNone(row["origin_platform"])
                self.assertEqual(row["origin_platform_method"], "verified_correction")
                connection.close()
            finally:
                kp_sync.DB_FILE = old_db

    def test_wikipedia_rejects_same_name_wrong_type_or_year(self):
        movie = {"original_title": "The Odyssey", "year": 2026, "media_type": "movie", "imdb_id": "tt1234567"}
        self.assertFalse(kp_sync.wikipedia_matches_media(movie, "The Odyssey (TV series)",
            "{{Infobox television\n| first_aired = 1997\n| network = NBC\n}}\nReissued in 2026. tt1234567"))
        self.assertFalse(kp_sync.wikipedia_matches_media(movie, "The Odyssey (film)",
            "{{Infobox film\n| released = 1997\n}}\nReferenced in 2026. tt1234567"))
        self.assertFalse(kp_sync.wikipedia_matches_media(movie, "The Odyssey (film)",
            "{{Infobox film\n| released = 2026\n}} tt7654321"))
        self.assertTrue(kp_sync.wikipedia_matches_media(movie, "The Odyssey (2026 film)",
            "{{Infobox film\n| released = {{Film date|2026|7|17}}\n}} tt1234567"))

    def test_series_state_uses_episode_dates(self):
        today = date(2026, 9, 21)
        metadata = kp_sync.parse_kinopoisk_page(SAMPLE_PAGE, 123, "tv")
        state = kp_sync.series_state(metadata, today=today)
        self.assertEqual(state["airing_state"], "airing")
        self.assertEqual(state["last_episode_number"], 4)
        self.assertEqual(state["next_episode_number"], 5)

    def test_rating_five_is_neutral(self):
        self.assertEqual(kp_sync.RATING_SCALE[5][1], 0.0)
        self.assertGreater(kp_sync.RATING_SCALE[6][1], 0.0)
        self.assertGreater(kp_sync.RATING_SCALE[7][1], kp_sync.RATING_SCALE[6][1])

    def test_rating_xml_fallback(self):
        original = kp_sync.curl
        try:
            kp_sync.curl = lambda *args, **kwargs: (
                '<ratings><kp_rating num_vote="10">7.4</kp_rating>'
                '<imdb_rating num_vote="20">8.2</imdb_rating></ratings>'
            )
            metadata = {"kp_id": 123, "kp_rating": None, "imdb_rating": None}
            kp_sync.supplement_kinopoisk_ratings(metadata, Path('/tmp/test-cookie'))
            self.assertEqual(metadata["kp_rating"], 7.4)
            self.assertEqual(metadata["imdb_rating"], 8.2)
        finally:
            kp_sync.curl = original

    def test_schema_and_migration_open(self):
        with tempfile.TemporaryDirectory() as directory:
            old_db = kp_sync.DB_FILE
            try:
                kp_sync.DB_FILE = Path(directory) / "test.sqlite3"
                connection = kp_sync.open_database()
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")
                }
                columns = {row[1] for row in connection.execute("PRAGMA table_info(media)")}
                connection.close()
                self.assertIn("metadata_runs", tables)
                self.assertIn("series_tracking", tables)
                self.assertIn("metadata_status", columns)
                self.assertIn("origin_platform", columns)
            finally:
                kp_sync.DB_FILE = old_db

    def test_feature_calibration_keeps_five_neutral(self):
        with tempfile.TemporaryDirectory() as directory:
            old_db = kp_sync.DB_FILE
            try:
                kp_sync.DB_FILE = Path(directory) / "calibration.sqlite3"
                connection = kp_sync.open_database()
                with connection:
                    connection.execute("INSERT INTO profiles VALUES('p','P','local',1,1)")
                    for rating, (label, utility) in kp_sync.RATING_SCALE.items():
                        connection.execute("INSERT INTO rating_scale VALUES('p',?,?,?)", (rating, label, utility))
                    connection.execute(
                        "INSERT INTO features(feature_type,external_id,name) VALUES('genre','fantasy','Фантастика')"
                    )
                    feature_id = connection.execute("SELECT feature_id FROM features").fetchone()[0]
                    for kp_id, rating in ((1, 5), (2, 6), (3, 7)):
                        connection.execute(
                            "INSERT INTO media(kp_id,media_type,title) VALUES(?,'movie',?)",
                            (kp_id, f"Фильм {kp_id}"),
                        )
                        connection.execute(
                            "INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('p',?,?)",
                            (kp_id, rating),
                        )
                        connection.execute(
                            "INSERT INTO media_features VALUES(?,?,1.0,'kinopoisk')",
                            (kp_id, feature_id),
                        )
                    kp_sync.calculate_feature_stats(connection, "p")
                    row = connection.execute(
                        "SELECT mean_utility,affinity_multiplier FROM profile_feature_stats"
                    ).fetchone()
                connection.close()
                self.assertAlmostEqual(row[0], (0.0 + 0.2 + 0.45) / 3, places=6)
                self.assertGreater(row[1], 1.0)
            finally:
                kp_sync.DB_FILE = old_db

    def test_card_ratings_returns_personal_score(self):
        with tempfile.TemporaryDirectory() as directory:
            old_db = kp_sync.DB_FILE
            try:
                kp_sync.DB_FILE = Path(directory) / "cards.sqlite3"
                connection = kp_sync.open_database()
                with connection:
                    connection.execute("INSERT INTO profiles VALUES('1234567','Roman','local',1,1)")
                    connection.execute(
                        """INSERT INTO media(
                             kp_id,media_type,title,release_year,kp_rating,imdb_rating,
                             metadata_status,metadata_revision,origin_platform,
                             origin_platform_label,origin_platform_confidence,
                             origin_platform_method,origin_platform_checked_at
                           ) VALUES(123,'movie','Тестовый фильм',2024,7.8,8.1,'ready',7,
                                    'netflix','Netflix',1.0,'explicit_network',1)"""
                    )
                    connection.execute(
                        "INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('1234567',123,9)"
                    )
                connection.close()
                result = kp_sync.card_ratings({
                    "title": ["Тестовый фильм"], "year": ["2024"], "type": ["movie"]
                })
                self.assertTrue(result["found"])
                self.assertEqual(result["kp_rating"], 7.8)
                self.assertEqual(result["imdb_rating"], 8.1)
                self.assertEqual(result["my_rating"], 9)
                self.assertEqual(result["origin_platform"], "netflix")
                self.assertFalse(result["refresh_pending"])
            finally:
                kp_sync.DB_FILE = old_db

    def test_stale_card_returns_ratings_without_waiting_for_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            old_db = kp_sync.DB_FILE
            original_schedule = kp_sync.schedule_card_refresh
            scheduled = []
            try:
                kp_sync.DB_FILE = Path(directory) / "cards-stale.sqlite3"
                connection = kp_sync.open_database()
                with connection:
                    connection.execute("INSERT INTO profiles VALUES('1234567','Roman','local',1,1)")
                    connection.execute(
                        """INSERT INTO media(
                             kp_id,media_type,title,release_year,kp_rating,imdb_rating,
                             metadata_status,metadata_revision,origin_platform_checked_at
                           ) VALUES(4541515,'tv','Укрытие',2023,7.816,8.1,'ready',6,1)"""
                    )
                    connection.execute(
                        "INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('1234567',4541515,8)"
                    )
                connection.close()
                kp_sync.schedule_card_refresh = lambda kp_id, media_type: scheduled.append((kp_id, media_type))
                result = kp_sync.card_ratings({
                    "kp_id": ["4541515"], "type": ["tv"]
                })
                self.assertEqual(result["kp_rating"], 7.816)
                self.assertEqual(result["my_rating"], 8)
                self.assertTrue(result["refresh_pending"])
                self.assertEqual(scheduled, [(4541515, "tv")])
            finally:
                kp_sync.schedule_card_refresh = original_schedule
                kp_sync.DB_FILE = old_db

    def test_cached_only_does_not_fetch_or_schedule(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.object(kp_sync, 'DB_FILE', Path(directory)/'cache-only.db'):
            connection = kp_sync.open_database()
            with connection:
                connection.execute("INSERT INTO profiles VALUES('1234567','Roman','local',1,1)")
                connection.execute("INSERT INTO media(kp_id,media_type,title,kp_rating,metadata_revision) VALUES(12,'tv','Existing',7.8,1)")
                connection.execute("INSERT INTO user_ratings(profile_id,kp_id,rating) VALUES('1234567',12,8)")
            connection.close()
            with patch.object(kp_sync,'lampac_external_ids',side_effect=AssertionError('Network lookup')), patch.object(kp_sync,'schedule_card_refresh',side_effect=AssertionError('Refresh')):
                self.assertFalse(kp_sync.card_ratings({'kp_id':['999'],'cached':['1']})['found'])
                self.assertEqual(kp_sync.card_ratings({'kp_id':['12'],'cached':['1'],'refresh':['1']})['my_rating'],8)


if __name__ == "__main__":
    unittest.main()

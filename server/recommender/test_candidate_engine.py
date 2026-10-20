import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import candidate_engine


ROOT = Path(__file__).resolve().parent


class CandidateEngineTests(unittest.TestCase):
    def test_prediction_independent_of_age_and_popularity(self):
        connection=self.connection()
        for kp_id,year,votes in ((3001,1960,1000000),(3002,2026,100)):
            connection.execute("INSERT INTO media(kp_id,media_type,title,release_year,kp_rating,kp_vote_count,metadata_status) VALUES(?,'movie','Same',?,7,?,'ready')",(kp_id,year,votes))
            connection.execute("INSERT INTO candidate_catalog VALUES(?,'popular_movies','Popular',1,1,1,1,1)",(kp_id,))
        connection.commit()
        top,_=candidate_engine.calculate_recommendations(connection,'owner',10)
        self.assertAlmostEqual(top[0]['predicted_rating'],top[1]['predicted_rating'])
        self.assertEqual(top[0]['kp_id'],3002)
        self.assertIsNone(candidate_engine.predict_card(connection,'owner',3001,7))
        connection.close()

    def connection(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        connection.executescript(candidate_engine.candidate_schema_sql())
        connection.execute(
            "INSERT INTO profiles VALUES('owner','Owner','https://example.test',1,1)"
        )
        return connection

    def test_parse_candidate_links(self):
        html = '''
        <a href="/film/example-123456/">Movie</a>
        <a href="https://www.kinopoisk.ru/series/show-654321/">Series</a>
        <a href="/film/example-123456/">Duplicate</a>
        '''
        self.assertEqual(
            candidate_engine.parse_candidate_ids(html, "movie"),
            [(123456, "movie"), (654321, "tv")],
        )

    def test_scoring_excludes_seen_and_prefers_affinity(self):
        connection = self.connection()
        for kp_id, title, rating in (
            (1001, "Seen", 8.0),
            (2001, "Favourite genre", 7.0),
            (2002, "Wrong genre", 8.5),
        ):
            connection.execute(
                """INSERT INTO media(kp_id,media_type,title,release_year,kp_rating,kp_vote_count,metadata_status)
                   VALUES(?, 'movie', ?, 2025, ?, 100000, 'ready')""",
                (kp_id, title, rating),
            )
        connection.execute("INSERT INTO user_ratings(profile_id,kp_id,rating,source) VALUES('owner',1001,8,'test')")
        connection.execute("INSERT INTO features(feature_id,feature_type,external_id,name) VALUES(1,'genre','science-fiction','Science fiction')")
        connection.execute("INSERT INTO features(feature_id,feature_type,external_id,name) VALUES(2,'genre','drama','Drama')")
        connection.execute("INSERT INTO media_features VALUES(2001,1,1.0,'test')")
        connection.execute("INSERT INTO media_features VALUES(2002,2,1.0,'test')")
        connection.execute(
            """INSERT INTO profile_feature_stats VALUES
               ('owner',1,30,30,8,0.7,0.8,0.1,1,0.8,1.30,1,1),
               ('owner',2,30,30,5,0.0,0.3,0.3,1,0.8,0.75,1,1)"""
        )
        for rank, kp_id in enumerate((1001, 2001, 2002), 1):
            connection.execute(
                "INSERT INTO candidate_catalog VALUES(?, 'popular_movies', 'Popular', ?, 1, 1, 1, 1)",
                (kp_id, rank),
            )
        connection.commit()

        top, count = candidate_engine.calculate_recommendations(connection, "owner", 10)
        self.assertEqual(count, 2)
        self.assertEqual(top[0]["kp_id"], 2001)
        self.assertNotIn(1001, [item["kp_id"] for item in top])

        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "recommendations.json"
            md_path = Path(directory) / "recommendations.md"
            report = candidate_engine.write_recommendation_reports(
                connection, "owner", json_path, md_path, 10
            )
            self.assertFalse(report["recommendations_enabled"])
            self.assertEqual(report["groups"][0]["items"][0]["kp_id"], 2001)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["stage"], "review_only")
            self.assertIn("Favourite genre", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

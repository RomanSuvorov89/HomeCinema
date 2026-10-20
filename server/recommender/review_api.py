"""Server-owned profile feedback, independent of Kinopoisk ratings."""
import json
import time

STATUSES = {"want", "not_interested", "seen", "clear"}


def ensure_schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS recommendation_feedback (
        profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
        kp_id INTEGER NOT NULL REFERENCES media(kp_id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('want','not_interested','seen')),
        updated_at INTEGER NOT NULL,
        PRIMARY KEY(profile_id,kp_id)
    )""")
    connection.commit()


def save_feedback(connection, profile_id, payload):
    kp_id = payload.get("kp_id")
    status = payload.get("status")
    if type(kp_id) is not int or kp_id <= 0 or status not in STATUSES:
        raise ValueError("Invalid kp_id or status")
    if not connection.execute("SELECT 1 FROM media WHERE kp_id=?", (kp_id,)).fetchone():
        raise ValueError("Unknown film")
    ensure_schema(connection)
    with connection:
        if status == "clear":
            connection.execute("DELETE FROM recommendation_feedback WHERE profile_id=? AND kp_id=?", (profile_id, kp_id))
        else:
            connection.execute("""INSERT INTO recommendation_feedback VALUES(?,?,?,?)
                ON CONFLICT(profile_id,kp_id) DO UPDATE SET
                status=excluded.status,updated_at=excluded.updated_at""",
                (profile_id, kp_id, status, int(time.time())))
    return {"ok": True, "kp_id": kp_id, "status": None if status == "clear" else status}


def review_data(connection, profile_id, report):
    ensure_schema(connection)
    # Read the actual contributing features only; do not present unused country/decade signals.
    allowed = {"genre", "genre_pair", "format", "keyword", "theme_genre", "creator", "director", "network", "franchise"}
    items = []
    originals = next((g["items"] for g in report.get("groups", []) if g["code"] == "for_me"), [])
    scored = connection.execute("""SELECT m.kp_id,m.title,m.original_title,m.release_year,m.media_type,
        m.kp_vote_count,s.final_score,s.predicted_rating,s.reasons_json
        FROM candidate_scores s JOIN media m USING(kp_id)
        WHERE s.profile_id=? AND s.formula_version=(SELECT MAX(formula_version) FROM candidate_scores WHERE profile_id=?)
        AND NOT EXISTS(SELECT 1 FROM user_ratings r WHERE r.profile_id=s.profile_id AND r.kp_id=s.kp_id)
        ORDER BY s.final_score DESC,m.kp_id""", (profile_id, profile_id)).fetchall()
    if scored:
        originals = []
        for row in scored:
            item = dict(row)
            item['reasons'] = json.loads(item.pop('reasons_json'))
            originals.append(item)
    for original in originals:
        item = dict(original)
        row = connection.execute("""SELECT m.overview,m.poster_path,m.tmdb_id,m.imdb_id,
            m.kp_rating,m.imdb_rating,m.origin_platform,m.origin_platform_label,
            m.origin_platform_confidence,ur.rating my_rating,f.status feedback
            FROM media m LEFT JOIN user_ratings ur ON ur.kp_id=m.kp_id AND ur.profile_id=?
            LEFT JOIN recommendation_feedback f ON f.kp_id=m.kp_id AND f.profile_id=?
            WHERE m.kp_id=?""", (profile_id, profile_id, item["kp_id"])).fetchone()
        if row:
            item.update(dict(row))
        item['countries'] = [r[0] for r in connection.execute("""SELECT f.name FROM features f
            JOIN media_features mf USING(feature_id) WHERE mf.kp_id=? AND f.feature_type='country'
            ORDER BY f.name""", (item['kp_id'],))]
        item['genres'] = [r[0] for r in connection.execute("""SELECT f.name FROM features f
            JOIN media_features mf USING(feature_id) WHERE mf.kp_id=? AND f.feature_type='genre'
            ORDER BY f.name""", (item['kp_id'],))]
        item["prediction_stage"] = "preliminary"
        item["reasons"] = dict(item.get("reasons") or {})
        for key in ("positive_features", "negative_features"):
            item["reasons"][key] = [f for f in item["reasons"].get(key, []) if f["type"] in allowed]
        items.append(item)
    return {"profile_id": profile_id, "items": items, "catalog": report.get("catalog", {}),
            "generated_at": report.get("generated_at"), "stage": "review_only"}

#!/usr/bin/env python3
import bisect
import json
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode


RECOMMENDATION_FORMULA_VERSION = 4

CANDIDATE_SOURCES = (
    ("top250_movies", "Топ-250 фильмов", "movie", "https://www.kinopoisk.ru/lists/movies/top250/", 1.03),
    ("top250_series", "Топ-250 сериалов", "tv", "https://www.kinopoisk.ru/lists/movies/series-top250/", 1.03),
    ("popular_movies", "Популярные фильмы", "movie", "https://www.kinopoisk.ru/lists/movies/popular-films/", 1.00),
    ("popular_series", "Популярные сериалы", "tv", "https://www.kinopoisk.ru/lists/movies/popular-series/", 1.00),
)

FEATURE_WEIGHTS = {
    "genre": 0.75,
    "genre_pair": 1.05,
    "keyword": 1.20,
    "theme_genre": 1.35,
    "creator": 0.90,
    "director": 0.95,
    "country": 0.45,
    "language": 0.35,
    "decade": 0.35,
    "network": 0.60,
    "franchise": 1.00,
    "format": 0.55,
}

GENRE_TYPES = {"genre", "genre_pair", "format"}
THEME_TYPES = {"keyword", "theme_genre", "creator", "director", "network", "franchise"}


def candidate_schema_sql():
    return """
    CREATE TABLE IF NOT EXISTS prediction_calibration (
        profile_id TEXT PRIMARY KEY, model_json TEXT NOT NULL, calculated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS candidate_catalog (
        kp_id INTEGER NOT NULL REFERENCES media(kp_id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        source_label TEXT NOT NULL,
        source_rank INTEGER NOT NULL,
        source_weight REAL NOT NULL DEFAULT 1.0,
        discovered_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (kp_id, source)
    );
    CREATE INDEX IF NOT EXISTS idx_candidate_catalog_active
        ON candidate_catalog(active, source, source_rank);
    """


def parse_candidate_ids(html, expected_type):
    patterns = (
        r'href=["\'](?:https://www\.kinopoisk\.ru)?/(film|series)/(?:[^"\']*?-)?(\d+)/',
        r'["\']url["\']\s*:\s*["\']/(film|series)/(?:[^"\']*?-)?(\d+)/',
    )
    result = []
    seen = set()
    for pattern in patterns:
        for kind, raw_id in re.findall(pattern, html, re.I):
            kp_id = int(raw_id)
            if kp_id < 1000 or kp_id in seen:
                continue
            seen.add(kp_id)
            media_type = "tv" if kind.casefold() == "series" else "movie"
            result.append((kp_id, media_type))
    if len(result) < 5:
        fallback = re.findall(r'["\'](?:kinopoiskId|filmId)["\']\s*:\s*["\']?(\d+)', html, re.I)
        for raw_id in fallback:
            kp_id = int(raw_id)
            if kp_id >= 1000 and kp_id not in seen:
                seen.add(kp_id)
                result.append((kp_id, expected_type))
    return result


def refresh_candidate_catalog(connection, fetch, pages=5):
    connection.executescript(candidate_schema_sql())
    started = int(time.time())
    summary = []
    for source, label, expected_type, base_url, source_weight in CANDIDATE_SOURCES:
        ordered = []
        seen = set()
        source_errors = []
        for page in range(1, pages + 1):
            url = base_url + ("?" + urlencode({"page": page}) if page > 1 else "")
            try:
                html = fetch(url)
                page_items = parse_candidate_ids(html, expected_type)
                if not page_items:
                    raise RuntimeError(f"candidate list page {page} contains no recognizable film links")
                for item in page_items:
                    if item[0] not in seen:
                        seen.add(item[0])
                        ordered.append(item)
            except Exception as error:
                source_errors.append(f"page {page}: {str(error)[:200]}")
                break

        if source_errors:
            summary.append({"source": source, "label": label, "status": "preserved", "errors": source_errors})
            continue

        with connection:
            connection.execute("UPDATE candidate_catalog SET active=0 WHERE source=?", (source,))
            for rank, (kp_id, media_type) in enumerate(ordered, 1):
                connection.execute(
                    """INSERT INTO media(kp_id,media_type,title,metadata_status)
                       VALUES(?,?,?,'pending')
                       ON CONFLICT(kp_id) DO NOTHING""",
                    (kp_id, media_type, f"Кинопоиск #{kp_id}"),
                )
                connection.execute(
                    """INSERT INTO candidate_catalog(
                           kp_id,source,source_label,source_rank,source_weight,
                           discovered_at,last_seen_at,active
                       ) VALUES(?,?,?,?,?,?,?,1)
                       ON CONFLICT(kp_id,source) DO UPDATE SET
                         source_label=excluded.source_label,
                         source_rank=excluded.source_rank,
                         source_weight=excluded.source_weight,
                         last_seen_at=excluded.last_seen_at,
                         active=1""",
                    (kp_id, source, label, rank, source_weight, started, started),
                )
        summary.append({"source": source, "label": label, "status": "updated", "count": len(ordered)})
    return summary


def weighted_multiplier(features, allowed_types):
    selected = [item for item in features if item["feature_type"] in allowed_types]
    if not selected:
        return 1.0
    weight_sum = 0.0
    log_sum = 0.0
    for item in selected:
        weight = FEATURE_WEIGHTS.get(item["feature_type"], 0.5) * float(item.get("media_weight") or 1.0)
        multiplier = max(0.35, min(1.80, float(item.get("affinity_multiplier") or 1.0)))
        weight_sum += weight
        log_sum += math.log(multiplier) * weight
    return math.exp(log_sum / weight_sum) if weight_sum else 1.0


def percentile(sorted_values, value):
    if not sorted_values:
        return 0.5
    if len(sorted_values) == 1:
        return 0.5
    return bisect.bisect_right(sorted_values, value) / len(sorted_values)


def personal_score(features, rating):
    genre = weighted_multiplier(features, GENRE_TYPES)
    theme = weighted_multiplier(features, THEME_TYPES)
    quality = max(0.80, min(1.25, 0.75 + 0.05 * float(rating or 5.0)))
    score = 100.0 * genre * theme * quality
    # Preliminary preference estimate. Popularity and age only affect placement.
    prediction = max(1.0, min(10.0, 5.0 + 2.5 * math.log(max(score, 1.0) / 100.0)))
    return genre, theme, quality, score, prediction


FEATURE_K = {'genre':12,'genre_pair':8,'keyword':6,'theme_genre':5,'creator':5,
             'director':5,'country':12,'language':15,'decade':15,'network':7,'franchise':5,'format':12}


def fit_rating_model(points):
    """Regularized monotone calibration of log preference to the owner's rating scale."""
    if not points: return {'count':0,'mean_x':0,'mean_rating':5,'slope':2.5,'method':'uncalibrated'}
    n=len(points)
    mx=sum(x for x,y in points)/n
    my=sum(y for x,y in points)/n
    variance=sum((x-mx)**2 for x,y in points)/n
    covariance=sum((x-mx)*(y-my) for x,y in points)/n
    # Sparse or constant features cannot support stretching the score range.
    slope=max(0,min(12,covariance/(variance+0.001))) if n>=20 else 0
    return {'count':n,'mean_x':mx,'mean_rating':my,'slope':slope,
            'method':'leave_one_out_features_ridge','feature_variance':variance}


def calibrated_prediction(score, model):
    x=math.log(max(score,1)/100)
    return max(1,min(10,model['mean_rating']+model['slope']*(x-model['mean_x'])))


def calibrate_ratings(connection, profile_id):
    ratings=connection.execute("""SELECT ur.kp_id,ur.rating,m.kp_rating,rs.utility
        FROM user_ratings ur JOIN media m USING(kp_id)
        LEFT JOIN rating_scale rs ON rs.profile_id=ur.profile_id AND rs.rating=ur.rating
        WHERE ur.profile_id=? AND m.metadata_status='ready' ORDER BY ur.kp_id""",(profile_id,)).fetchall()
    features=defaultdict(list)
    for r in connection.execute("""SELECT mf.kp_id,f.feature_type,mf.weight media_weight,
            p.effective_count,p.mean_utility,rs.utility
        FROM media_features mf JOIN features f USING(feature_id)
        JOIN user_ratings ur ON ur.kp_id=mf.kp_id AND ur.profile_id=?
        JOIN rating_scale rs ON rs.profile_id=ur.profile_id AND rs.rating=ur.rating
        JOIN profile_feature_stats p ON p.feature_id=f.feature_id AND p.profile_id=ur.profile_id AND p.formula_version=1""",(profile_id,)):
        effective=max(0,float(r['effective_count'])-float(r['media_weight']))
        total=float(r['mean_utility'])*float(r['effective_count'])-float(r['utility'])*float(r['media_weight'])
        affinity=1+0.65*total/(effective+FEATURE_K.get(r['feature_type'],10)) if effective>0 else 1
        features[r['kp_id']].append({'feature_type':r['feature_type'],'media_weight':r['media_weight'],
                                   'affinity_multiplier':max(.35,min(1.8,affinity))})
    points=[]
    for r in ratings:
        fs=features[r['kp_id']]
        if not any(f['feature_type'] in GENRE_TYPES|THEME_TYPES for f in fs): continue
        raw=personal_score(fs,r['kp_rating'])[3]
        points.append((math.log(max(raw,1)/100),r['rating']))
    model=fit_rating_model(points)
    if not points and ratings:
        model.update(count=0,mean_rating=sum(r['rating'] for r in ratings)/len(ratings),slope=0,method='profile_mean_only')
    # Holdout diagnostics: calibration fit never sees the held-out targets.
    if len(points)>=25:
        train=[p for i,p in enumerate(points) if i%5]
        test=[p for i,p in enumerate(points) if not i%5]
        validation=fit_rating_model(train)
        model['validation_count']=len(test)
        model['validation_mae']=sum(abs(calibrated_prediction(100*math.exp(x),validation)-y) for x,y in test)/len(test)
        model['baseline_mae']=sum(abs(validation['mean_rating']-y) for x,y in test)/len(test)
        model['validation_note']='Feature affinities remove own rating; shared feature statistics are not a full temporal holdout.'
    with connection:
        connection.execute('INSERT OR REPLACE INTO prediction_calibration VALUES(?,?,?)',
                           (profile_id,json.dumps(model),int(time.time())))
    return model


def stored_rating_model(connection, profile_id):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prediction_calibration'").fetchone(): return None
    row=connection.execute('SELECT model_json FROM prediction_calibration WHERE profile_id=?',(profile_id,)).fetchone()
    return json.loads(row[0]) if row else None


def predict_card(connection, profile_id, kp_id, rating):
    features = [dict(r) for r in connection.execute('''SELECT f.feature_type,f.name,
        mf.weight media_weight,p.affinity_multiplier,p.confidence,p.sample_count
        FROM media_features mf JOIN features f USING(feature_id)
        JOIN profile_feature_stats p ON p.feature_id=f.feature_id
        WHERE mf.kp_id=? AND p.profile_id=? AND p.formula_version=1''', (kp_id, profile_id))]
    if not any(f['feature_type'] in GENRE_TYPES | THEME_TYPES and (f['confidence'] or 0) > 0 for f in features):
        return None
    model=stored_rating_model(connection,profile_id)
    return round(calibrated_prediction(personal_score(features,rating)[3],model),2) if model else None


def calculate_recommendations(connection, profile_id, limit=50):
    connection.executescript(candidate_schema_sql())
    rows = connection.execute(
        """SELECT m.kp_id,m.media_type,m.title,m.original_title,m.release_year,
                  m.kp_rating,m.kp_vote_count,m.imdb_rating,m.origin_platform_label,
                  MIN(cc.source_rank) best_source_rank,
                  MAX(cc.source_weight) source_weight,
                  GROUP_CONCAT(DISTINCT cc.source_label) source_labels
           FROM media m JOIN candidate_catalog cc USING(kp_id)
           WHERE cc.active=1 AND m.metadata_status='ready'
             AND NOT EXISTS (SELECT 1 FROM user_ratings ur WHERE ur.profile_id=? AND ur.kp_id=m.kp_id)
             AND NOT EXISTS (SELECT 1 FROM watchlist w WHERE w.profile_id=? AND w.kp_id=m.kp_id)
           GROUP BY m.kp_id""",
        (profile_id, profile_id),
    ).fetchall()

    feature_rows = connection.execute(
        """SELECT mf.kp_id,f.feature_type,f.name,mf.weight media_weight,
                  COALESCE(p.affinity_multiplier,1.0) affinity_multiplier,
                  COALESCE(p.confidence,0.0) confidence,
                  COALESCE(p.sample_count,0) sample_count
           FROM media_features mf JOIN features f USING(feature_id)
           LEFT JOIN profile_feature_stats p
             ON p.feature_id=f.feature_id AND p.profile_id=? AND p.formula_version=1
           WHERE mf.kp_id IN (SELECT kp_id FROM candidate_catalog WHERE active=1)""",
        (profile_id,),
    ).fetchall()
    features_by_media = defaultdict(list)
    for row in feature_rows:
        features_by_media[row["kp_id"]].append(dict(row))

    vote_buckets = defaultdict(list)
    for row in rows:
        decade = (row["release_year"] or 0) // 10 * 10
        vote_buckets[(row["media_type"], decade)].append(math.log1p(row["kp_vote_count"] or 0))
    for values in vote_buckets.values():
        values.sort()

    model=calibrate_ratings(connection,profile_id)
    calculated_at = int(time.time())
    scored = []
    for row in rows:
        features = features_by_media[row["kp_id"]]
        genre_multiplier, theme_multiplier, quality_multiplier, preference_score, predicted_rating = personal_score(features, row['kp_rating'])
        predicted_rating=calibrated_prediction(preference_score,model)
        decade = (row["release_year"] or 0) // 10 * 10
        votes_log = math.log1p(row["kp_vote_count"] or 0)
        mass_percentile = percentile(vote_buckets[(row["media_type"], decade)], votes_log)
        mass_multiplier = 0.95 + 0.40 * mass_percentile
        source_multiplier = float(row["source_weight"] or 1.0)
        age = max(0, datetime.now(timezone.utc).year - row['release_year']) if row['release_year'] else None
        freshness = 1.0 + 0.35 * math.exp(-age / 3.0) if age is not None else 1.0
        final_score = preference_score * mass_multiplier * source_multiplier * freshness

        positive = sorted(
            [item for item in features if item["affinity_multiplier"] > 1.005 and item["confidence"] > 0],
            key=lambda item: (item["affinity_multiplier"] - 1) * FEATURE_WEIGHTS.get(item["feature_type"], 0.5),
            reverse=True,
        )[:4]
        negative = sorted(
            [item for item in features if item["affinity_multiplier"] < 0.995 and item["confidence"] > 0],
            key=lambda item: item["affinity_multiplier"],
        )[:2]
        reasons = {
            "positive_features": [
                {"type": item["feature_type"], "name": item["name"], "multiplier": round(item["affinity_multiplier"], 3)}
                for item in positive
            ],
            "negative_features": [
                {"type": item["feature_type"], "name": item["name"], "multiplier": round(item["affinity_multiplier"], 3)}
                for item in negative
            ],
            "kp_rating": row["kp_rating"],
            "kp_vote_count": row["kp_vote_count"],
            "mass_percentile": round(mass_percentile, 4),
            "freshness_multiplier": round(freshness, 4),
            "preference_score": round(preference_score, 4),
            "prediction_stage": "preliminary",
            "calibration": model,
            "sources": (row["source_labels"] or "").split(","),
        }
        item = dict(row)
        item.update({
            "predicted_rating": predicted_rating,
            "genre_multiplier": genre_multiplier,
            "theme_multiplier": theme_multiplier,
            "mass_multiplier": mass_multiplier,
            "rating_confidence": quality_multiplier,
            "novelty_multiplier": source_multiplier,
            "final_score": final_score,
            "reasons": reasons,
        })
        scored.append(item)

    scored.sort(key=lambda item: item["final_score"], reverse=True)
    with connection:
        connection.execute(
            "DELETE FROM candidate_scores WHERE profile_id=? AND formula_version=?",
            (profile_id, RECOMMENDATION_FORMULA_VERSION),
        )
        for item in scored:
            connection.execute(
                """INSERT INTO candidate_scores(
                       profile_id,kp_id,predicted_rating,genre_multiplier,theme_multiplier,
                       mass_multiplier,rating_confidence,novelty_multiplier,final_score,
                       reasons_json,calculated_at,formula_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    profile_id, item["kp_id"], item["predicted_rating"], item["genre_multiplier"],
                    item["theme_multiplier"], item["mass_multiplier"], item["rating_confidence"],
                    item["novelty_multiplier"], item["final_score"],
                    json.dumps(item["reasons"], ensure_ascii=False), calculated_at,
                    RECOMMENDATION_FORMULA_VERSION,
                ),
            )
    return scored[:limit], len(scored)


def recommendation_report(connection, profile_id, limit=50):
    top, scored_count = calculate_recommendations(connection, profile_id, max(limit, 100))
    catalog_total = connection.execute(
        "SELECT COUNT(DISTINCT kp_id) FROM candidate_catalog WHERE active=1"
    ).fetchone()[0]
    catalog_ready = connection.execute(
        """SELECT COUNT(DISTINCT cc.kp_id) FROM candidate_catalog cc
           JOIN media m USING(kp_id) WHERE cc.active=1 AND m.metadata_status='ready'"""
    ).fetchone()[0]

    def public(item):
        return {
            "kp_id": item["kp_id"],
            "media_type": item["media_type"],
            "title": item["title"],
            "original_title": item["original_title"],
            "release_year": item["release_year"],
            "kp_rating": item["kp_rating"],
            "kp_vote_count": item["kp_vote_count"],
            "imdb_rating": item["imdb_rating"],
            "origin_platform_label": item["origin_platform_label"],
            "predicted_rating": round(item["predicted_rating"], 2),
            "genre_multiplier": round(item["genre_multiplier"], 4),
            "theme_multiplier": round(item["theme_multiplier"], 4),
            "mass_multiplier": round(item["mass_multiplier"], 4),
            "final_score": round(item["final_score"], 3),
            "reasons": item["reasons"],
        }

    for_me = top[:limit]
    popular = sorted(
        [item for item in top if item["genre_multiplier"] >= 1.0],
        key=lambda item: item["mass_multiplier"] * item["final_score"], reverse=True,
    )[: min(25, limit)]
    risky = sorted(
        [item for item in top if item["mass_multiplier"] >= 1.15 and item["genre_multiplier"] < 1.04],
        key=lambda item: item["final_score"], reverse=True,
    )[: min(20, limit)]
    return {
        "generated_at": int(time.time()),
        "formula_version": RECOMMENDATION_FORMULA_VERSION,
        "profile_id": profile_id,
        "stage": "review_only",
        "recommendations_enabled": False,
        "catalog": {"total": catalog_total, "ready": catalog_ready, "remaining": catalog_total - catalog_ready},
        "scored_count": scored_count,
        "groups": [
            {"code": "for_me", "title": "Для меня", "items": [public(item) for item in for_me]},
            {"code": "popular_for_me", "title": "Популярное в моих жанрах", "items": [public(item) for item in popular]},
            {"code": "worth_a_try", "title": "Можно рискнуть", "items": [public(item) for item in risky]},
        ],
    }


def report_markdown(report):
    catalog = report["catalog"]
    lines = [
        "# Предварительные рекомендации", "",
        f"Сформирован: {datetime.fromtimestamp(report['generated_at'], timezone.utc).isoformat()}", "",
        "Выдача в Lampa выключена: это отчёт для ручной проверки.", "",
        f"Каталог: {catalog['ready']} готово из {catalog['total']}; осталось {catalog['remaining']}.", "",
    ]
    for group in report["groups"]:
        lines += [f"## {group['title']}", "", "| # | Название | Год | КП | Голоса | Прогноз | Score | Почему |", "|---:|---|---:|---:|---:|---:|---:|---|"]
        for number, item in enumerate(group["items"], 1):
            reasons = ", ".join(feature["name"] for feature in item["reasons"]["positive_features"][:3]) or "массовость и рейтинг"
            lines.append(
                f"| {number} | {item['title']} | {item['release_year'] or '—'} | "
                f"{item['kp_rating'] or '—'} | {item['kp_vote_count'] or 0} | "
                f"{item['predicted_rating']:.2f} | {item['final_score']:.2f} | {reasons} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_recommendation_reports(connection, profile_id, json_path, markdown_path, limit=50):
    report = recommendation_report(connection, profile_id, limit)
    for path, content in (
        (Path(json_path), json.dumps(report, ensure_ascii=False, indent=2)),
        (Path(markdown_path), report_markdown(report)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    return report

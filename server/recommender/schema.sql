PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rating_scale (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 10),
    label TEXT NOT NULL,
    utility REAL NOT NULL,
    PRIMARY KEY (profile_id, rating)
);

CREATE TABLE IF NOT EXISTS media (
    kp_id INTEGER PRIMARY KEY,
    media_type TEXT NOT NULL CHECK (media_type IN ('movie', 'tv')),
    tmdb_id INTEGER,
    imdb_id TEXT,
    title TEXT NOT NULL,
    original_title TEXT,
    release_year INTEGER,
    release_date TEXT,
    original_language TEXT,
    overview TEXT,
    poster_path TEXT,
    runtime_minutes INTEGER,
    kp_rating REAL,
    kp_vote_count INTEGER,
    tmdb_rating REAL,
    tmdb_vote_count INTEGER,
    tmdb_popularity REAL,
    imdb_rating REAL,
    metadata_source TEXT,
    metadata_status TEXT NOT NULL DEFAULT 'pending',
    metadata_error TEXT,
    metadata_attempts INTEGER NOT NULL DEFAULT 0,
    metadata_revision INTEGER NOT NULL DEFAULT 0,
    origin_platform TEXT,
    origin_platform_label TEXT,
    origin_platform_confidence REAL,
    origin_platform_method TEXT,
    origin_platform_evidence TEXT,
    origin_platform_checked_at INTEGER,
    mapping_status TEXT NOT NULL DEFAULT 'pending',
    mapping_confidence REAL,
    mapping_method TEXT,
    mapping_reason TEXT,
    mapping_checked_at INTEGER,
    metadata_updated_at INTEGER,
    UNIQUE (media_type, tmdb_id)
);

CREATE TABLE IF NOT EXISTS user_ratings (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    kp_id INTEGER NOT NULL REFERENCES media(kp_id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 10),
    rated_at_text TEXT,
    rated_at INTEGER,
    source TEXT NOT NULL DEFAULT 'kinopoisk',
    PRIMARY KEY (profile_id, kp_id)
);

CREATE TABLE IF NOT EXISTS watchlist (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    kp_id INTEGER NOT NULL REFERENCES media(kp_id) ON DELETE CASCADE,
    added_at INTEGER,
    source TEXT NOT NULL DEFAULT 'kinopoisk',
    PRIMARY KEY (profile_id, kp_id)
);

CREATE TABLE IF NOT EXISTS features (
    feature_id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_type TEXT NOT NULL,
    external_id TEXT,
    name TEXT NOT NULL,
    is_generic INTEGER NOT NULL DEFAULT 0,
    UNIQUE (feature_type, external_id),
    UNIQUE (feature_type, name)
);

CREATE TABLE IF NOT EXISTS media_features (
    kp_id INTEGER NOT NULL REFERENCES media(kp_id) ON DELETE CASCADE,
    feature_id INTEGER NOT NULL REFERENCES features(feature_id) ON DELETE CASCADE,
    weight REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL DEFAULT 'tmdb',
    PRIMARY KEY (kp_id, feature_id)
);

CREATE TABLE IF NOT EXISTS profile_feature_stats (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    feature_id INTEGER NOT NULL REFERENCES features(feature_id) ON DELETE CASCADE,
    sample_count INTEGER NOT NULL,
    effective_count REAL NOT NULL,
    mean_rating REAL NOT NULL,
    mean_utility REAL NOT NULL,
    positive_rate REAL NOT NULL,
    negative_rate REAL NOT NULL,
    frequency_lift REAL NOT NULL,
    confidence REAL NOT NULL,
    affinity_multiplier REAL NOT NULL,
    calculated_at INTEGER NOT NULL,
    formula_version INTEGER NOT NULL,
    PRIMARY KEY (profile_id, feature_id, formula_version)
);

CREATE TABLE IF NOT EXISTS candidate_scores (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    kp_id INTEGER NOT NULL REFERENCES media(kp_id) ON DELETE CASCADE,
    predicted_rating REAL NOT NULL,
    genre_multiplier REAL NOT NULL,
    theme_multiplier REAL NOT NULL,
    mass_multiplier REAL NOT NULL,
    rating_confidence REAL NOT NULL,
    novelty_multiplier REAL NOT NULL,
    final_score REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    calculated_at INTEGER NOT NULL,
    formula_version INTEGER NOT NULL,
    PRIMARY KEY (profile_id, kp_id, formula_version)
);

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

CREATE TABLE IF NOT EXISTS mapping_review (
    kp_id INTEGER PRIMARY KEY REFERENCES media(kp_id) ON DELETE CASCADE,
    proposed_tmdb_id INTEGER,
    proposed_media_type TEXT,
    confidence REAL NOT NULL,
    method TEXT NOT NULL,
    reason TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    resolution TEXT
);

CREATE TABLE IF NOT EXISTS metadata_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS series_tracking (
    profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    kp_id INTEGER NOT NULL REFERENCES media(kp_id) ON DELETE CASCADE,
    tracking_mode TEXT NOT NULL DEFAULT 'auto'
        CHECK (tracking_mode IN ('auto', 'follow', 'muted')),
    airing_state TEXT NOT NULL DEFAULT 'dormant'
        CHECK (airing_state IN ('airing', 'dormant', 'ended', 'canceled', 'unknown')),
    tmdb_status TEXT,
    in_production INTEGER,
    current_season INTEGER,
    last_episode_number INTEGER,
    last_air_date TEXT,
    next_episode_number INTEGER,
    next_air_date TEXT,
    active_from TEXT,
    active_until TEXT,
    state_reason TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (profile_id, kp_id)
);

CREATE TABLE IF NOT EXISTS enrichment_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,
    mapped_exact INTEGER NOT NULL DEFAULT 0,
    mapped_probable INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    enriched_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metadata_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,
    selected_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    ready_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_ratings_rating
    ON user_ratings(profile_id, rating);
CREATE INDEX IF NOT EXISTS idx_media_mapping
    ON media(mapping_status, media_type);
CREATE INDEX IF NOT EXISTS idx_media_features_feature
    ON media_features(feature_id, kp_id);
CREATE INDEX IF NOT EXISTS idx_candidate_scores_rank
    ON candidate_scores(profile_id, formula_version, final_score DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_catalog_active
    ON candidate_catalog(active, source, source_rank);
CREATE INDEX IF NOT EXISTS idx_mapping_review_resolution
    ON mapping_review(resolved_at, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_series_tracking_state
    ON series_tracking(profile_id, airing_state, next_air_date);
CREATE INDEX IF NOT EXISTS idx_metadata_cache_expiry
    ON metadata_cache(expires_at);

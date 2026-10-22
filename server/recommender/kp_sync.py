#!/usr/bin/env python3
import html
import itertools
import json
import math
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from candidate_engine import (
    candidate_schema_sql,
    refresh_candidate_catalog,
    write_recommendation_reports,
)


PROFILE_ID = os.environ.get("KINOPOISK_PROFILE_ID", "")
PROFILE_DISPLAY_NAME = os.environ.get("PROFILE_DISPLAY_NAME", "Kinopoisk user")
DATA_FILE = Path(os.environ.get("DATA_FILE", "/data/kinopoisk.json"))
DB_FILE = Path(os.environ.get("DB_FILE", "/data/recommender.sqlite3"))
APP_DIR = Path(__file__).resolve().parent
PLUGIN_FILE = Path(os.environ.get("PLUGIN_FILE", APP_DIR / "kinopoisk.js"))
SCHEMA_FILE = Path(os.environ.get("SCHEMA_FILE", APP_DIR / "schema.sql"))
REPORT_JSON_FILE = Path(os.environ.get("REPORT_JSON_FILE", "/data/calibration-report.json"))
REPORT_MD_FILE = Path(os.environ.get("REPORT_MD_FILE", "/data/calibration-report.md"))
RECOMMENDATIONS_JSON_FILE = Path(os.environ.get("RECOMMENDATIONS_JSON_FILE", "/data/recommendations.json"))
RECOMMENDATIONS_MD_FILE = Path(os.environ.get("RECOMMENDATIONS_MD_FILE", "/data/recommendations.md"))
DB_BACKUP_DIR = Path(os.environ.get("DB_BACKUP_DIR", "/data/backups"))
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "86400"))
ENRICH_SECONDS = int(os.environ.get("ENRICH_SECONDS", "3600"))
ENRICH_BATCH_SIZE = int(os.environ.get("ENRICH_BATCH_SIZE", "100"))
ENRICH_WORKERS = int(os.environ.get("ENRICH_WORKERS", "10"))
ENRICH_CONTINUE_DELAY_SECONDS = float(os.environ.get("ENRICH_CONTINUE_DELAY_SECONDS", "5"))
KINOPOISK_METADATA_RPM = float(os.environ.get("KINOPOISK_METADATA_RPM", "12"))
WIKIPEDIA_METADATA_RPM = float(os.environ.get("WIKIPEDIA_METADATA_RPM", "20"))
TVMAZE_ENABLED = os.environ.get("TVMAZE_ENABLED", "0").strip().casefold() in ("1", "true", "yes")
METADATA_MAX_AGE = int(os.environ.get("METADATA_MAX_AGE", str(14 * 86400)))
SERIES_METADATA_MAX_AGE = int(os.environ.get("SERIES_METADATA_MAX_AGE", "21600"))
CANDIDATE_ENABLED = os.environ.get("CANDIDATE_ENABLED", "1").strip().casefold() in ("1", "true", "yes")
CANDIDATE_PAGES = int(os.environ.get("CANDIDATE_PAGES", "5"))
CANDIDATE_REFRESH_SECONDS = int(os.environ.get("CANDIDATE_REFRESH_SECONDS", "86400"))
ACTIVE_NEXT_DAYS = int(os.environ.get("ACTIVE_NEXT_DAYS", "45"))
ACTIVE_RECENT_DAYS = int(os.environ.get("ACTIVE_RECENT_DAYS", "30"))
BASE = f"https://www.kinopoisk.ru/user/{PROFILE_ID}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
FORMULA_VERSION = 1
METADATA_REVISION = 7
LAMPAC_URL = os.environ.get("LAMPAC_URL", "http://127.0.0.1:9118").rstrip("/")
CARD_LOOKUP_LOCK = threading.Lock()
CARD_REFRESH_LOCK = threading.Lock()
CARD_REFRESHING = set()
REQUEST_CONTEXT = threading.local()
DATABASE_INIT_LOCK = threading.Lock()
DATABASE_RUNS_CLEANED = False


class RateLimiter:
    def __init__(self, requests_per_minute):
        self.interval = 60.0 / max(float(requests_per_minute), 0.1)
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            scheduled = max(now, self.next_at)
            self.next_at = scheduled + self.interval
        delay = scheduled - now
        if delay > 0:
            time.sleep(delay)


KINOPOISK_METADATA_LIMITER = RateLimiter(KINOPOISK_METADATA_RPM)
WIKIPEDIA_METADATA_LIMITER = RateLimiter(WIKIPEDIA_METADATA_RPM)


RATING_SCALE = {
    1: ("Абсолютное дно", -1.00),
    2: ("Смотреть почти невозможно", -0.80),
    3: ("Очень сильное отторжение", -0.60),
    4: ("Плохой, бредовый фильм", -0.35),
    5: ("Никакой; только факт просмотра", 0.00),
    6: ("Интересны отдельные моменты", 0.20),
    7: ("Прикольный фильм", 0.45),
    8: ("Заставил задуматься", 0.70),
    9: ("Неизгладимое впечатление", 0.90),
    10: ("Шедевр", 1.00),
}

RATING_SCALE_FILE = os.environ.get("RATING_SCALE_FILE", "").strip()
if RATING_SCALE_FILE:
    raw_scale = json.loads(Path(RATING_SCALE_FILE).read_text(encoding="utf-8"))
    loaded_scale = {
        int(rating): (str(value["label"]), float(value["utility"]))
        for rating, value in raw_scale.items()
    }
    if set(loaded_scale) != set(range(1, 11)):
        raise RuntimeError("rating scale must define every rating from 1 through 10")
    RATING_SCALE = loaded_scale


FEATURE_K = {
    "genre": 12.0,
    "genre_pair": 8.0,
    "keyword": 6.0,
    "theme_genre": 5.0,
    "creator": 5.0,
    "director": 5.0,
    "country": 12.0,
    "language": 15.0,
    "decade": 15.0,
    "network": 7.0,
    "franchise": 5.0,
    "format": 12.0,
}

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

THEME_PATTERNS = {
    "путешествия во времени": r"time[ -]?trav(?:el|elling)|time loop|временн(?:ая|ой) петл|путешеств\w* во времени",
    "космос": r"spacecraft|spaceship|astronaut|outer space|космич|космос|астронавт",
    "искусственный интеллект": r"artificial intelligence|\bai\b|искусственн\w+ интеллект",
    "антиутопия": r"dystopi|антиутоп",
    "постапокалипсис": r"post[ -]?apocal|постапокалип|после апокалипсиса",
    "апокалипсис": r"apocalyp|конец света|апокалип",
    "параллельные миры": r"parallel (?:world|univers)|alternate (?:world|reality)|параллельн\w+ мир|альтернативн\w+ реальност",
    "инопланетяне": r"\balien|extraterrestrial|инопланет|пришелец",
    "роботы": r"\brobot|android|робот|андроид",
    "выживание": r"\bsurviv|выживан|выжить",
    "детективное расследование": r"detective|investigat|murder mystery|детектив|расследован",
    "серийный убийца": r"serial killer|серийн\w+ убийц",
    "ограбление": r"\bheist|ограблен",
    "шпионаж": r"\bspy\b|espionage|шпион",
    "политика": r"politic|government conspir|политик|правительственн\w+ заговор",
    "война": r"\bwar\b|soldier|военн|война|солдат",
    "супергерои": r"superhero|супергеро",
    "магия": r"\bmagic|sorcer|witch|маг|волшеб|ведьм",
    "вампиры": r"vampire|вампир",
    "зомби": r"zombie|зомби",
    "медицина": r"hospital|doctor|medical|больниц|врач|медицин",
    "семейные отношения": r"family relationship|dysfunctional family|семейн\w+ отношен",
    "романтические отношения": r"romantic relationship|love story|романтическ\w+ отношен|история любви",
}

# Порядок важен: стриминги проверяются раньше одноимённых телеканалов/студий.
# Слишком общие студии вроде Walt Disney Pictures и Paramount Pictures намеренно
# отсутствуют: их наличие не означает релиз как Disney+ или Paramount+ Original.
ORIGIN_BRANDS = [
    ("apple_tv", "Apple TV+", (r"\bapple\s+tv\+?\b", r"\bapple\s+studios?\b")),
    ("netflix", "Netflix", (r"\bnetflix\b",)),
    ("prime_video", "Prime Video", (r"\bprime\s+video\b", r"\bamazon\s+studios?\b")),
    ("disney_plus", "Disney+", (r"\bdisney\s*\+", r"\bdisney\s+plus\b")),
    ("hulu", "Hulu", (r"\bhulu\b",)),
    ("max", "Max", (r"\bhbo\s+max\b", r"^max$")),
    ("paramount_plus", "Paramount+", (r"\bparamount\s*\+", r"\bparamount\s+plus\b")),
    ("peacock", "Peacock", (r"\bpeacock\b",)),
    ("kinopoisk", "Кинопоиск", (r"\bкинопоиск(?:\s+hd)?\b",)),
    ("okko", "Okko", (r"\bokko(?:\s+studios?)?\b",)),
    ("start", "START", (r"^start$", r"\bstart\s+studio\b")),
    ("premier", "PREMIER", (r"^premier$", r"\bpremier\s+studios?\b")),
    ("wink", "Wink", (r"\bwink(?:\s+originals?)?\b",)),
    ("hbo", "HBO", (r"\bhbo\b", r"\bhbo\s+entertainment\b")),
    ("amc", "AMC", (r"^amc(?:\+)?$", r"\bamc\s+studios?\b")),
    ("fx", "FX", (r"^fx$", r"\bfx\s+network\b", r"\bfx\s+productions?\b")),
    ("bbc", "BBC", (r"^bbc(?:\s+(?:one|two|three|america))?$", r"\bbbc\s+studios?\b")),
    ("showtime", "Showtime", (r"\bshowtime\b",)),
    ("starz", "Starz", (r"\bstarz\b",)),
    ("nbc", "NBC", (r"^nbc$", r"\bnbc\s+universal\s+television\b")),
    ("cbs", "CBS", (r"^cbs$", r"\bcbs\s+studios?\b")),
    ("abc", "ABC", (r"^abc$", r"\babc\s+studios?\b")),
    ("fox", "FOX", (r"^fox$", r"\bfox\s+television\b")),
    ("cw", "The CW", (r"^(?:the\s+)?cw$",)),
]


def _float_or_none(value):
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _int_or_none(value):
    try:
        return int(re.sub(r"\D+", "", str(value)))
    except (TypeError, ValueError):
        return None


def normalized_text(value):
    return " ".join(str(value or "").replace("\xa0", " ").split())


def normalized_key(value):
    return " ".join(re.findall(r"[\w]+", str(value or "").casefold(), re.UNICODE))


def listify(value):
    if value is None:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(listify(item))
        return result
    if isinstance(value, dict):
        for key in ("name", "genre", "country", "value", "title"):
            if value.get(key):
                return [normalized_text(value[key])]
        return []
    return [part for part in (normalized_text(item) for item in re.split(r",\s*", str(value))) if part]


class VotesParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.div_stack = []
        self.item_depth = None
        self.current = None
        self.in_name_anchor = False
        self.in_rating_b = False
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "div":
            self.div_stack.append(classes)
            if "item" in classes and self.current is None:
                self.item_depth = len(self.div_stack)
                self.current = {key: [] for key in (
                    "title_parts", "original_parts", "date_parts", "vote_parts",
                    "kp_rating_parts", "kp_votes_parts",
                )}
        if self.current and tag == "a" and any("nameRus" in classes for classes in self.div_stack):
            match = re.fullmatch(r"/(film|series)/(\d+)/", attrs.get("href", ""))
            if match:
                self.current["media_type"] = "tv" if match.group(1) == "series" else "movie"
                self.current["kp_id"] = int(match.group(2))
                self.in_name_anchor = True
        if self.current and tag == "b" and any("rating" in classes for classes in self.div_stack):
            self.in_rating_b = True

    def handle_data(self, data):
        if not self.current:
            return
        classes = [item for group in self.div_stack for item in group]
        if self.in_name_anchor:
            self.current["title_parts"].append(data)
        elif "nameEng" in classes:
            self.current["original_parts"].append(data)
        elif "date" in classes:
            self.current["date_parts"].append(data)
        elif "vote" in classes:
            self.current["vote_parts"].append(data)
        elif self.in_rating_b:
            self.current["kp_rating_parts"].append(data)
        elif "rating" in classes:
            self.current["kp_votes_parts"].append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_name_anchor = False
        if tag == "b":
            self.in_rating_b = False
        if tag != "div" or not self.div_stack:
            return
        closing = self.current and len(self.div_stack) == self.item_depth
        self.div_stack.pop()
        if not closing:
            return
        title = normalized_text("".join(self.current["title_parts"]))
        if re.search(r"\b(?:сериал|мини-сериал)\b",title,re.I):
            self.current["media_type"]="tv"
        year = re.search(r"\([^)]*?(\d{4})", title)
        vote = re.search(r"\b(10|[1-9])\b", " ".join(self.current["vote_parts"]))
        kp_votes = re.search(r"([0-9][0-9\s\xa0]*)", " ".join(self.current["kp_votes_parts"]))
        if self.current.get("kp_id") and vote:
            self.rows.append({
                "kp_id": self.current["kp_id"],
                "media_type": self.current.get("media_type", "movie"),
                "title": re.sub(r"\s*\([^)]*\)\s*$", "", title),
                "original_title": normalized_text("".join(self.current["original_parts"])),
                "year": int(year.group(1)) if year else None,
                "rating": int(vote.group(1)),
                "rated_at": normalized_text("".join(self.current["date_parts"])),
                "kp_rating": _float_or_none("".join(self.current["kp_rating_parts"])),
                "kp_vote_count": _int_or_none(kp_votes.group(1)) if kp_votes else None,
            })
        self.current = None
        self.item_depth = None


class WatchlistParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.div_stack = []
        self.li_depth = 0
        self.item_depth = None
        self.current = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "div":
            self.div_stack.append(classes)
        if tag == "li":
            self.li_depth += 1
        if tag == "li" and "item" in classes and attrs.get("id", "").startswith("film_"):
            self.item_depth = self.li_depth
            self.current = {"kp_id": int(attrs["id"].split("_", 1)[1]), "title_parts": [], "info_parts": []}
        if self.current and tag == "a" and "name" in classes:
            self.current["in_name"] = True
            self.current["media_type"] = "tv" if attrs.get("href", "").startswith("/series/") else "movie"

    def handle_data(self, data):
        if not self.current:
            return
        classes = [item for group in self.div_stack for item in group]
        if self.current.get("in_name"):
            self.current["title_parts"].append(data)
        if "info" in classes:
            self.current["info_parts"].append(data)

    def handle_endtag(self, tag):
        if self.current and tag == "a":
            self.current["in_name"] = False
        if tag == "div" and self.div_stack:
            self.div_stack.pop()
        closing = tag == "li" and self.current and self.li_depth == self.item_depth
        if tag == "li":
            self.li_depth -= 1
        if closing:
            info = normalized_text("".join(self.current["info_parts"]))
            years = re.findall(r"\b(19\d{2}|20\d{2})\b", info)
            self.rows.append({
                "kp_id": self.current["kp_id"],
                "media_type": self.current.get("media_type", "movie"),
                "title": normalized_text("".join(self.current["title_parts"])),
                "year": int(years[0]) if years else None,
            })
            self.current = None
            self.item_depth = None


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and (
            attrs.get("type", "").casefold() == "application/ld+json"
            or attrs.get("id") == "__NEXT_DATA__"
        ):
            self.capture = True
            self.parts = []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.capture:
            raw = html.unescape("".join(self.parts)).strip()
            try:
                self.scripts.append(json.loads(raw))
            except (TypeError, ValueError):
                pass
            self.capture = False
            self.parts = []


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def first_value(objects, keys, predicate=None):
    for obj in objects:
        for key in keys:
            value = obj.get(key)
            if value not in (None, "", [], {}) and (predicate is None or predicate(value)):
                return value
    return None


def collect_named(objects, keys):
    result = []
    seen = set()
    for obj in objects:
        for key in keys:
            if key not in obj:
                continue
            for name in listify(obj[key]):
                marker = name.casefold()
                if marker not in seen:
                    seen.add(marker)
                    result.append(name)
    return result


def longest_text(objects, keys):
    candidates = []
    for obj in objects:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(normalized_text(value))
    return max(candidates, key=len, default="")


def iso_duration_minutes(value):
    match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?", str(value or ""))
    if not match:
        return _int_or_none(value)
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def parse_date(value):
    match = re.search(r"(19\d{2}|20\d{2})-(\d{2})-(\d{2})", str(value or ""))
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        return None


def match_origin_brand(values):
    for value in values:
        normalized = normalized_text(value)
        folded = normalized.casefold()
        for code, label, patterns in ORIGIN_BRANDS:
            if any(re.search(pattern, folded, re.I) for pattern in patterns):
                return code, label, normalized
    return None


def detect_origin_platform(networks, companies, distributors, description):
    matched = match_origin_brand(networks)
    if matched:
        code, label, evidence = matched
        return {
            "code": code, "label": label, "confidence": 1.0,
            "method": "explicit_network", "evidence": evidence,
        }
    matched = match_origin_brand(companies)
    if matched:
        code, label, evidence = matched
        return {
            "code": code, "label": label, "confidence": 0.9,
            "method": "production_company", "evidence": evidence,
        }
    folded = normalized_text(description).casefold()
    context_markers = re.compile(
        r"оригинальн|сериал|фильм|проект|шоу|original|series|movie|film|show", re.I
    )
    if context_markers.search(folded):
        matched = match_origin_brand([folded])
        if matched:
            code, label, evidence = matched
            return {
                "code": code, "label": label, "confidence": 0.7,
                "method": "description", "evidence": evidence[:240],
            }
    return {
        "code": None, "label": None, "confidence": 0.0,
        "method": "not_detected", "evidence": None,
    }


def origin_from_tvmaze(payload):
    if not isinstance(payload, dict):
        return None
    for key, method in (("webChannel", "tvmaze_web_channel"), ("network", "tvmaze_network")):
        source = payload.get(key)
        if not isinstance(source, dict):
            continue
        name = normalized_text(source.get("name") or "")
        matched = match_origin_brand([name])
        if matched:
            code, label, evidence = matched
            return {
                "code": code,
                "label": label,
                "confidence": 1.0,
                "method": method,
                "evidence": evidence,
            }
    return None


def clean_wikitext(value):
    text = str(value or "")
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<ref\b[^>]*>.*?</ref>|<ref\b[^>]*/>", " ", text, flags=re.I | re.S)
    text = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\{\{(?:nowrap|small|plainlist|ubl|unbulleted list)\s*\|([^{}]+)\}\}", r"\1", text, flags=re.I)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"<br\s*/?>", ", ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalized_text(html.unescape(text).replace("'''", "").replace("''", ""))


def wikipedia_infobox_values(wikitext, keys):
    wanted = {key.casefold() for key in keys}
    values = []
    lines = str(wikitext or "").splitlines()
    index = 0
    while index < len(lines):
        match = re.match(r"^\s*\|\s*([\w ]+)\s*=\s*(.*)$", lines[index])
        if not match or match.group(1).strip().casefold() not in wanted:
            index += 1
            continue
        parts = [match.group(2)]
        index += 1
        while index < len(lines) and not re.match(r"^\s*\|\s*[\w ]+\s*=", lines[index]) and not re.match(r"^\s*\}\}", lines[index]):
            parts.append(lines[index])
            index += 1
        value = clean_wikitext(" ".join(parts))
        if value:
            values.extend(listify(value))
    return values


def wikipedia_matches_media(metadata, page_title, wikitext):
    """Require identity, not a title substring and a year anywhere in an article."""
    imdb_id = normalized_text(metadata.get("imdb_id") or "").casefold()
    ids = set(re.findall(r"\btt\d{7,10}\b", wikitext.casefold()))
    # An unrelated IMDb mention in an article must never override kind/title/year.
    title = metadata.get("original_title") or metadata.get("title") or ""
    bare_title = re.sub(r"\s*\([^)]*\)\s*$", "", page_title)
    if normalized_key(title) != normalized_key(bare_title):
        return False
    tv = metadata.get("media_type") == "tv"
    infobox = r"\{\{\s*(?:infobox\s+television|телесериал|телевизионное шоу)\b" if tv else r"\{\{\s*(?:infobox\s+film|фильм)\b"
    if not re.search(infobox, wikitext, re.I):
        return False
    if imdb_id and ids and imdb_id not in ids:
        return False
    dates = wikipedia_infobox_values(wikitext, ("first_aired", "first aired", "released", "release_date", "release date", "первый показ", "премьера", "год"))
    # Preserve years inside date templates stripped by the text cleaner.
    date_fields = re.findall(r"^\s*\|\s*(?:first_aired|first aired|released|release_date|release date|первый показ|премьера|год)\s*=([^\n]+)", wikitext, re.I | re.M)
    year = str(metadata.get("year") or "")
    years = re.findall(r"\b(?:19|20)\d{2}\b", " ".join(date_fields + dates))
    if year and years:
        return year == years[0]
    return bool(imdb_id and imdb_id in ids)


def origin_from_wikipedia(metadata):
    title = metadata.get("original_title") or metadata.get("title") or ""
    year = metadata.get("year") or ""
    kind = "TV series" if metadata.get("media_type") == "tv" else "film"
    imdb_id = normalized_text(metadata.get("imdb_id") or "")
    query = f'"{title}" {year} {kind}'.strip()
    errors = []
    for host in ("en.wikipedia.org", "ru.wikipedia.org"):
        try:
            search_url = f"https://{host}/w/api.php?" + urlencode({
                "action": "query", "list": "search", "srsearch": query,
                "srlimit": 3, "format": "json", "formatversion": 2,
            })
            search = json.loads(curl_public(search_url))
            candidates = search.get("query", {}).get("search", [])
            for candidate in candidates[:2]:
                page_title = candidate.get("title")
                if not page_title:
                    continue
                parse_url = f"https://{host}/w/api.php?" + urlencode({
                    "action": "parse", "page": page_title, "prop": "wikitext",
                    "format": "json", "formatversion": 2,
                })
                parsed = json.loads(curl_public(parse_url))
                wikitext = parsed.get("parse", {}).get("wikitext", "")
                if not wikitext:
                    continue
                if not wikipedia_matches_media(metadata, page_title, wikitext):
                    continue
                networks = wikipedia_infobox_values(
                    wikitext, ("network", "original network", "channel", "original channel")
                )
                companies = wikipedia_infobox_values(
                    wikitext, ("company", "companies", "production company", "production companies")
                )
                distributors = wikipedia_infobox_values(wikitext, ("distributor", "distributed by"))
                detected = detect_origin_platform(networks, companies, distributors, "")
                if detected.get("code"):
                    detected["confidence"] = 0.95
                    detected["method"] = "wikipedia_infobox"
                    return detected, {
                        "source": "wikipedia",
                        "host": host,
                        "page": page_title,
                        "network": networks,
                        "companies": companies,
                        "distributors": distributors,
                    }, errors
        except Exception as error:
            errors.append(f"{host}: {str(error)[:160]}")
    return None, None, errors


def supplement_origin_platform(metadata):
    origin = metadata.get("origin_platform") or {}
    if origin.get("code"):
        return metadata
    imdb_id = normalized_text(metadata.get("imdb_id") or "")
    has_imdb_id = bool(re.fullmatch(r"tt\d+", imdb_id))
    errors = []
    if TVMAZE_ENABLED and metadata.get("media_type") == "tv" and has_imdb_id:
        try:
            payload = json.loads(curl_public(
                "https://api.tvmaze.com/lookup/shows?" + urlencode({"imdb": imdb_id})
            ))
            detected = origin_from_tvmaze(payload)
            if detected:
                metadata["origin_platform"] = detected
                metadata["origin_platform_external"] = {
                    "source": "tvmaze",
                    "show_id": payload.get("id"),
                    "url": payload.get("url"),
                }
                print(
                    f"origin platform: kp_id={metadata.get('kp_id')} source=tvmaze platform={detected['label']}",
                    flush=True,
                )
                return metadata
        except Exception as error:
            errors.append(f"tvmaze: {str(error)[:160]}")
    detected, source, wikipedia_errors = origin_from_wikipedia(metadata)
    errors.extend(wikipedia_errors)
    if detected:
        metadata["origin_platform"] = detected
        metadata["origin_platform_external"] = source
        print(
            f"origin platform: kp_id={metadata.get('kp_id')} source=wikipedia platform={detected['label']}",
            flush=True,
        )
    if errors:
        metadata["origin_platform_lookup_error"] = "; ".join(errors)[:500]
    if metadata.get("_interactive") and not (metadata.get("origin_platform") or {}).get("code"):
        print(
            f"origin platform unresolved: kp_id={metadata.get('kp_id')} "
            f"errors={metadata.get('origin_platform_lookup_error') or 'no matching network'}",
            flush=True,
        )
    return metadata


def parse_kinopoisk_page(text, kp_id, media_type):
    parser = ScriptParser()
    parser.feed(text)
    objects = [obj for script in parser.scripts for obj in walk_json(script)]
    schemas = [
        obj for obj in objects
        if str(obj.get("@type", "")).casefold() in ("movie", "tvseries", "creativeworkseries")
    ]
    primary = schemas[0] if schemas else {}
    matching_roots = [
        obj for obj in objects
        if str(obj.get("id") or obj.get("filmId") or obj.get("kinopoiskId") or "") == str(kp_id)
    ]
    relevant_roots = schemas + matching_roots
    likely = [obj for root in relevant_roots for obj in walk_json(root)] if relevant_roots else objects
    description = longest_text(likely, ("description", "synopsis", "overview"))
    title = normalized_text(first_value(likely, ("name", "title", "nameRu")) or "")
    original_title = normalized_text(first_value(likely, ("alternativeHeadline", "originalName", "nameOriginal")) or "")
    genres = collect_named(likely[:100], ("genre", "genres"))
    countries = collect_named(likely[:100], ("countries", "country", "countryOfOrigin"))
    directors = collect_named(likely[:200], ("director", "directors"))
    creators = collect_named(likely[:200], ("creator", "creators"))
    # Only fields owned by the selected movie/series. Global caches may contain
    # networks of unrelated recommendations and must not brand this card.
    origin_roots = ([primary] if primary else []) + matching_roots
    networks = collect_named(origin_roots, ("network", "networks", "tvNetwork", "broadcastChannel", "channel", "channels"))
    companies = collect_named(origin_roots, ("productionCompany", "productionCompanies", "studio", "studios", "company", "companies"))
    distributors = collect_named(origin_roots, ("distributor", "distributors"))
    origin = detect_origin_platform(networks, companies, distributors, description)
    aggregate = first_value(likely, ("aggregateRating",), lambda item: isinstance(item, dict)) or {}
    kp_rating = _float_or_none(
        aggregate.get("ratingValue")
        or first_value(likely, ("ratingKinopoisk", "ratingKp", "rating"), lambda item: not isinstance(item, (dict, list)))
    )
    kp_votes = _int_or_none(
        aggregate.get("ratingCount")
        or first_value(likely, ("ratingKinopoiskVoteCount", "votesCount", "ratingCount"))
    )
    imdb_rating = _float_or_none(
        first_value(
            likely,
            ("ratingImdb", "imdbRating", "ratingIMDb"),
            lambda item: not isinstance(item, (dict, list)),
        )
    )
    imdb_id = normalized_text(
        first_value(likely, ("imdbId", "imdb_id"), lambda item: not isinstance(item, (dict, list))) or ""
    )
    if not re.fullmatch(r"tt\d+", imdb_id):
        imdb_match = re.search(r"\btt\d{5,10}\b", text)
        imdb_id = imdb_match.group(0) if imdb_match else ""
    release = first_value(likely, ("dateCreated", "datePublished", "premiere", "startDate"))
    year = _int_or_none(first_value(likely, ("year", "startYear", "releaseYear")))
    if not year and release:
        year_match = re.search(r"(19\d{2}|20\d{2})", str(release))
        year = int(year_match.group(1)) if year_match else None
    end_year = _int_or_none(first_value(likely, ("endYear",)))
    runtime = iso_duration_minutes(primary.get("duration") or first_value(likely, ("filmLength", "runtime", "duration")))
    status = normalized_text(first_value(likely, ("status", "productionStatus", "seriesStatus")) or "")
    episodes = []
    seen_episodes = set()
    for obj in objects:
        season = _int_or_none(obj.get("seasonNumber") or obj.get("season"))
        episode = _int_or_none(obj.get("episodeNumber") or obj.get("episode"))
        air_date = parse_date(
            obj.get("airDate") or obj.get("releaseDate") or obj.get("datePublished") or obj.get("premiere")
        )
        if air_date and (season is not None or episode is not None):
            marker = (season, episode, air_date)
            if marker not in seen_episodes:
                seen_episodes.add(marker)
                episodes.append({"season": season, "episode": episode, "date": air_date.isoformat()})
    if not any((title, description, genres, countries, kp_rating, year)):
        raise ValueError("Kinopoisk page contains no recognized metadata")
    return {
        "kp_id": kp_id,
        "media_type": media_type,
        "title": title,
        "original_title": original_title,
        "description": description,
        "genres": genres,
        "countries": countries,
        "directors": directors,
        "creators": creators,
        "networks": networks,
        "production_companies": companies,
        "distributors": distributors,
        "origin_platform": origin,
        "kp_rating": kp_rating,
        "kp_vote_count": kp_votes,
        "imdb_rating": imdb_rating,
        "imdb_id": imdb_id or None,
        "release_date": parse_date(release).isoformat() if parse_date(release) else None,
        "year": year,
        "end_year": end_year,
        "runtime_minutes": runtime,
        "status": status,
        "episodes": sorted(episodes, key=lambda item: item["date"]),
    }


def extracted_themes(description):
    text = (description or "").casefold()
    return [name for name, pattern in THEME_PATTERNS.items() if re.search(pattern, text, re.I)]


def metadata_features(metadata):
    genres = metadata["genres"]
    themes = extracted_themes(metadata["description"])
    values = [("genre", normalized_key(name), name) for name in genres]
    values += [("keyword", normalized_key(name), name) for name in themes]
    for left, right in itertools.combinations(genres, 2):
        values.append((
            "genre_pair", "+".join(sorted((normalized_key(left), normalized_key(right)))),
            f"{left} + {right}",
        ))
    for theme, genre in itertools.product(themes, genres):
        values.append((
            "theme_genre", f"{normalized_key(theme)}+{normalized_key(genre)}",
            f"{theme} + {genre}",
        ))
    values += [("director", normalized_key(name), name) for name in metadata["directors"]]
    values += [("creator", normalized_key(name), name) for name in metadata["creators"]]
    values += [("country", normalized_key(name), name) for name in metadata["countries"]]
    origin = metadata.get("origin_platform") or {}
    if origin.get("code"):
        values.append(("network", origin["code"], origin["label"]))
    if metadata["year"]:
        decade = f"{metadata['year'] // 10 * 10}-е"
        values.append(("decade", decade, decade))
    lowered_genres = {name.casefold() for name in genres}
    if "мультфильм" in lowered_genres or "анимация" in lowered_genres:
        media_format = "анимация"
    else:
        media_format = "сериал" if metadata["media_type"] == "tv" else "фильм"
    values.append(("format", media_format, media_format))
    return [(kind, key, name) for kind, key, name in values if key and name]


def series_state(metadata, today=None):
    today = today or datetime.now(timezone.utc).date()
    episodes = [dict(item, parsed=parse_date(item["date"])) for item in metadata.get("episodes", [])]
    episodes.sort(key=lambda item: (item["parsed"] or today, item.get("season", 0), item.get("episode", 0)))
    previous = [item for item in episodes if item["parsed"] and item["parsed"] <= today]
    upcoming = [item for item in episodes if item["parsed"] and item["parsed"] > today]
    last_episode = previous[-1] if previous else None
    next_episode = upcoming[0] if upcoming else None
    # Only an already premiered season can be active. A future season's first
    # episode must never activate an older watched season.
    active_season = last_episode.get("season") if last_episode else None
    same_season_next = next_episode and last_episode and next_episode.get("season") == active_season
    premiered = [e for e in previous if e.get("season") == active_season]
    season_start = min((e["parsed"] for e in premiered), default=None)
    status = (metadata.get("status") or "").casefold()
    end_year = metadata.get("end_year")
    if any(word in status for word in ("cancel", "отмен")):
        state, reason = "canceled", "Кинопоиск помечает сериал как отменённый"
    elif any(word in status for word in ("completed", "finished", "ended", "заверш")):
        state, reason = "ended", "Кинопоиск помечает сериал как завершённый"
    elif same_season_next and next_episode["parsed"] <= today + timedelta(days=ACTIVE_NEXT_DAYS):
        state, reason = "airing", f"Следующая серия ожидается {next_episode['date']}"
    elif last_episode and last_episode["parsed"] >= today - timedelta(days=ACTIVE_RECENT_DAYS):
        state, reason = "airing", f"Новая серия выходила {last_episode['date']}"
    elif end_year and end_year < today.year:
        state, reason = "ended", f"Последний указанный год выхода — {end_year}"
    elif any(word in status for word in ("filming", "post", "production", "ongoing", "продолжа")):
        state, reason = "dormant", "Сериал продолжается, но сейчас нет подтверждённой даты серии"
    else:
        state, reason = "unknown", "На публичной странице нет достаточных данных о расписании"
    anchor = last_episode or next_episode or {}
    return {
        "airing_state": state,
        "tmdb_status": metadata.get("status"),
        "in_production": 1 if state in ("airing", "dormant") else 0,
        "current_season": anchor.get("season"),
        "last_episode_number": last_episode.get("episode") if last_episode else None,
        "last_air_date": last_episode.get("date") if last_episode else None,
        "next_episode_number": next_episode.get("episode") if next_episode else None,
        "next_air_date": next_episode.get("date") if next_episode else None,
        "active_from": season_start.isoformat() if state == "airing" and season_start else None,
        "active_until": (
            ((next_episode if same_season_next else last_episode or {"parsed": today})["parsed"] + timedelta(days=ACTIVE_RECENT_DAYS)).isoformat()
            if state == "airing" else None
        ),
        "state_reason": reason,
    }


def curl(url, cookie_file, save_cookies=True):
    if getattr(REQUEST_CONTEXT, "metadata", False):
        KINOPOISK_METADATA_LIMITER.wait()
    command = [
        "curl", "-fsSL", "--compressed", "--retry", "2", "--retry-all-errors",
        "--connect-timeout", "10", "--max-time", "30", "-A", UA,
        "-b", str(cookie_file), "-b", "sso_status=sso.passport.yandex.ru:synchronized",
    ]
    if save_cookies:
        command += ["-c", str(cookie_file)]
    command.append(url)
    process = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process.stdout.decode("utf-8", "replace")


def curl_public(url):
    if getattr(REQUEST_CONTEXT, "metadata", False) and "wikipedia.org" in url:
        WIKIPEDIA_METADATA_LIMITER.wait()
    process = subprocess.run([
        "curl", "-fsSL", "--compressed", "--retry", "2", "--retry-all-errors",
        "--connect-timeout", "10", "--max-time", "30", "-A", UA, url,
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process.stdout.decode("utf-8", "replace")


def establish_session(cookie_file, base=None):
    base = base or BASE
    target = f"{base}/votes/list/ord/date/page/1/"
    first = curl(target, cookie_file)
    if "profileFilmsList" in first:
        return first
    meta_match = re.search(r"var it = (\{.*?\});", first)
    container_match = re.search(r"element2\.value = '([^']+)'", first)
    if not meta_match or not container_match:
        raise RuntimeError("Kinopoisk SSO bootstrap was not recognized")
    meta = json.loads(meta_match.group(1))
    subprocess.run([
        "curl", "-fsS", "--compressed", "-A", UA,
        "-b", str(cookie_file), "-c", str(cookie_file),
        "--data-urlencode", f"retpath={meta['retpath']}",
        "--data-urlencode", f"container={container_match.group(1)}",
        meta["host"],
    ], check=True, stdout=subprocess.DEVNULL)
    result = curl(target, cookie_file)
    if "profileFilmsList" not in result:
        raise RuntimeError("Kinopoisk did not return the public votes page")
    return result


def supplement_kinopoisk_ratings(metadata, cookie_file):
    if metadata.get("kp_rating") and metadata.get("imdb_rating"):
        return metadata
    try:
        xml = curl(f"https://rating.kinopoisk.ru/{metadata['kp_id']}.xml", cookie_file, False)
    except Exception:
        return metadata
    if not metadata.get("kp_rating"):
        match = re.search(r"<kp_rating\b[^>]*>\s*([0-9.,]+)\s*</kp_rating>", xml, re.I)
        if match:
            metadata["kp_rating"] = _float_or_none(match.group(1))
    if not metadata.get("imdb_rating"):
        match = re.search(r"<imdb_rating\b[^>]*>\s*([0-9.,]+)\s*</imdb_rating>", xml, re.I)
        if match:
            metadata["imdb_rating"] = _float_or_none(match.group(1))
    return metadata


def total_count(text):
    match = re.search(r'class="pagesFromTo"[^>]*>.*?из\s+(\d+)', text, re.S)
    return int(match.group(1)) if match else 0


def sync(profile_id=None):
    profile_id = profile_id or PROFILE_ID
    from connections import read
    connection = direct_connection()
    try:
        public_id = read(connection, profile_id, PROFILE_ID)["kp_id"]
    finally:
        connection.close()
    base = "https://www.kinopoisk.ru/user/" + public_id
    with tempfile.TemporaryDirectory() as directory:
        cookie_file = Path(directory) / "cookies.txt"
        first = establish_session(cookie_file, base)
        expected_votes = total_count(first)
        pages = max(1, (expected_votes + 49) // 50)

        def parse_votes(page):
            text = first if page == 1 else curl(f"{base}/votes/list/ord/date/page/{page}/", cookie_file, False)
            parser = VotesParser()
            parser.feed(text)
            return parser.rows

        with ThreadPoolExecutor(max_workers=4) as pool:
            votes = [row for page in pool.map(parse_votes, range(1, pages + 1)) for row in page]
        first_watch = curl(f"{base}/movies/list/type/3575/sort/default/page/1/", cookie_file)
        expected_watch = total_count(first_watch)
        watch_pages = max(1, (expected_watch + 24) // 25)

        def parse_watch(page):
            text = first_watch if page == 1 else curl(
                f"{base}/movies/list/type/3575/sort/default/page/{page}/", cookie_file, False
            )
            parser = WatchlistParser()
            parser.feed(text)
            return parser.rows

        with ThreadPoolExecutor(max_workers=2) as pool:
            watchlist = [row for page in pool.map(parse_watch, range(1, watch_pages + 1)) for row in page]
    if len(votes) != expected_votes:
        raise RuntimeError(f"votes completeness check failed: parsed {len(votes)}, expected {expected_votes}")
    if len(watchlist) != expected_watch:
        raise RuntimeError(f"watchlist completeness check failed: parsed {len(watchlist)}, expected {expected_watch}")
    return {
        "profile_id": profile_id,
        "public_profile_id": public_id,
        "updated_at": int(time.time()),
        "ratings_count": len(votes),
        "watchlist_count": len(watchlist),
        "ratings": votes,
        "watchlist": watchlist,
    }


def open_database():
    global DATABASE_RUNS_CLEANED
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_FILE, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    connection.executescript(candidate_schema_sql())
    existing = {row[1] for row in connection.execute("PRAGMA table_info(media)")}
    migrations = {
        "mapping_method": "TEXT",
        "mapping_reason": "TEXT",
        "mapping_checked_at": "INTEGER",
        "imdb_rating": "REAL",
        "metadata_source": "TEXT",
        "metadata_status": "TEXT NOT NULL DEFAULT 'pending'",
        "metadata_error": "TEXT",
        "metadata_attempts": "INTEGER NOT NULL DEFAULT 0",
        "metadata_revision": "INTEGER NOT NULL DEFAULT 0",
        "origin_platform": "TEXT",
        "origin_platform_label": "TEXT",
        "origin_platform_confidence": "REAL",
        "origin_platform_method": "TEXT",
        "origin_platform_evidence": "TEXT",
        "origin_platform_checked_at": "INTEGER",
    }
    for column, sql_type in migrations.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE media ADD COLUMN {column} {sql_type}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_metadata_queue "
        "ON media(metadata_status, metadata_updated_at, metadata_attempts)"
    )
    connection.execute(
        "UPDATE media SET metadata_status='pending' "
        "WHERE metadata_status='ready' AND COALESCE(metadata_revision,0)<?",
        (METADATA_REVISION,),
    )
    with DATABASE_INIT_LOCK:
        if not DATABASE_RUNS_CLEANED:
            connection.execute(
                "UPDATE metadata_runs SET status='interrupted', finished_at=? WHERE status='running'",
                (int(time.time()),),
            )
            DATABASE_RUNS_CLEANED = True
    connection.commit()
    return connection


def persist_database(data):
    profile_id = data.get("profile_id", PROFILE_ID)
    public_id = data.get("public_profile_id", PROFILE_ID)
    now = int(time.time())
    connection = open_database()
    try:
        with connection:
            connection.execute(
                """INSERT INTO profiles(profile_id, display_name, source_url, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(profile_id) DO UPDATE SET display_name=excluded.display_name,
                     source_url=excluded.source_url, updated_at=excluded.updated_at""",
                (profile_id, PROFILE_DISPLAY_NAME, f"https://www.kinopoisk.ru/user/{public_id}/", now, now),
            )
            for rating, (label, utility) in RATING_SCALE.items():
                connection.execute(
                    """INSERT INTO rating_scale(profile_id, rating, label, utility) VALUES(?, ?, ?, ?)
                       ON CONFLICT(profile_id, rating) DO UPDATE SET label=excluded.label, utility=excluded.utility""",
                    (profile_id, rating, label, utility),
                )
            connection.execute("DELETE FROM user_ratings WHERE profile_id=?", (profile_id,))
            connection.execute("DELETE FROM watchlist WHERE profile_id=?", (profile_id,))
            for item in data["ratings"]:
                connection.execute(
                    """INSERT INTO media(kp_id, media_type, title, original_title, release_year, kp_rating, kp_vote_count)
                       VALUES(?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(kp_id) DO UPDATE SET
                         media_type=CASE WHEN media.media_type='tv' THEN 'tv' ELSE excluded.media_type END, title=excluded.title,
                         original_title=COALESCE(excluded.original_title, media.original_title),
                         release_year=COALESCE(excluded.release_year, media.release_year),
                         kp_rating=COALESCE(excluded.kp_rating, media.kp_rating),
                         kp_vote_count=COALESCE(excluded.kp_vote_count, media.kp_vote_count)""",
                    (
                        item["kp_id"], item["media_type"], item["title"], item.get("original_title") or None,
                        item.get("year"), item.get("kp_rating"), item.get("kp_vote_count"),
                    ),
                )
                connection.execute(
                    "INSERT INTO user_ratings(profile_id,kp_id,rating,rated_at_text,source) VALUES(?,?,?,?, 'kinopoisk')",
                    (profile_id, item["kp_id"], item["rating"], item.get("rated_at")),
                )
            for item in data["watchlist"]:
                connection.execute(
                    """INSERT INTO media(kp_id,media_type,title,release_year) VALUES(?,?,?,?)
                       ON CONFLICT(kp_id) DO UPDATE SET media_type=excluded.media_type,
                       title=excluded.title, release_year=COALESCE(excluded.release_year,media.release_year)""",
                    (item["kp_id"], item["media_type"], item["title"], item.get("year")),
                )
                connection.execute(
                    "INSERT INTO watchlist(profile_id,kp_id,added_at,source) VALUES(?,?,?,'kinopoisk')",
                    (profile_id, item["kp_id"], now),
                )
            connection.execute(
                """INSERT INTO sync_state(key,value,updated_at) VALUES('kinopoisk_last_sync',?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (str(data["updated_at"]), now),
            )
    finally:
        connection.close()


def replace_features(connection, kp_id, metadata):
    connection.execute("DELETE FROM media_features WHERE kp_id=?", (kp_id,))
    for feature_type, external_id, name in metadata_features(metadata):
        connection.execute(
            "INSERT OR IGNORE INTO features(feature_type,external_id,name) VALUES(?,?,?)",
            (feature_type, external_id, name),
        )
        feature = connection.execute(
            """SELECT feature_id FROM features WHERE feature_type=? AND (external_id=? OR name=?)
               ORDER BY CASE WHEN external_id=? THEN 0 ELSE 1 END LIMIT 1""",
            (feature_type, external_id, name, external_id),
        ).fetchone()
        connection.execute(
            "INSERT OR REPLACE INTO media_features(kp_id,feature_id,weight,source) VALUES(?,?,?,'kinopoisk')",
            (kp_id, feature[0], FEATURE_WEIGHTS.get(feature_type, 1.0)),
        )


def save_series_tracking(connection, profile_id, kp_id, state):
    connection.execute(
        """INSERT INTO series_tracking(
             profile_id,kp_id,airing_state,tmdb_status,in_production,current_season,
             last_episode_number,last_air_date,next_episode_number,next_air_date,
             active_from,active_until,state_reason,updated_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(profile_id,kp_id) DO UPDATE SET
             airing_state=excluded.airing_state,tmdb_status=excluded.tmdb_status,
             in_production=excluded.in_production,current_season=excluded.current_season,
             last_episode_number=excluded.last_episode_number,last_air_date=excluded.last_air_date,
             next_episode_number=excluded.next_episode_number,next_air_date=excluded.next_air_date,
             active_from=excluded.active_from,active_until=excluded.active_until,
             state_reason=excluded.state_reason,updated_at=excluded.updated_at""",
        (
            profile_id, kp_id, state["airing_state"], state["tmdb_status"], state["in_production"],
            state["current_season"], state["last_episode_number"], state["last_air_date"],
            state["next_episode_number"], state["next_air_date"], state["active_from"],
            state["active_until"], state["state_reason"], int(time.time()),
        ),
    )


def persist_metadata(connection, media, metadata):
    now = int(time.time())
    origin = metadata.get("origin_platform") or {}
    origin_evidence = json.dumps({
        "selected": origin.get("evidence"),
        "networks": metadata.get("networks", []),
        "production_companies": metadata.get("production_companies", []),
        "distributors": metadata.get("distributors", []),
        "external": metadata.get("origin_platform_external"),
        "lookup_error": metadata.get("origin_platform_lookup_error"),
    }, ensure_ascii=False)
    current = connection.execute("SELECT * FROM media WHERE kp_id=?", (media["kp_id"],)).fetchone()
    preserve = current and (current["origin_platform_method"] == "verified_correction" or (
        current["origin_platform"] and float(current["origin_platform_confidence"] or 0) >= 0.85
        and (not origin.get("code") or float(origin.get("confidence") or 0) < 0.85)
    ))
    if preserve:
        origin = {"code": current["origin_platform"], "label": current["origin_platform_label"],
                  "confidence": current["origin_platform_confidence"], "method": current["origin_platform_method"]}
        origin_evidence = current["origin_platform_evidence"]
    connection.execute(
        """UPDATE media SET
             title=COALESCE(NULLIF(?,''),title),
             original_title=COALESCE(NULLIF(?,''),original_title),
             release_year=COALESCE(?,release_year),release_date=COALESCE(?,release_date),
             overview=?,runtime_minutes=COALESCE(?,runtime_minutes),
             kp_rating=COALESCE(?,kp_rating),kp_vote_count=COALESCE(?,kp_vote_count),
             imdb_id=COALESCE(?,imdb_id),imdb_rating=COALESCE(?,imdb_rating),
             origin_platform=?,origin_platform_label=?,origin_platform_confidence=?,
             origin_platform_method=?,origin_platform_evidence=?,origin_platform_checked_at=?,
             mapping_status='native',mapping_confidence=1.0,mapping_method='kinopoisk_id',
             mapping_reason='Прямой идентификатор Кинопоиска',mapping_checked_at=?,
             metadata_source='kinopoisk',metadata_status='ready',metadata_error=NULL,
             metadata_attempts=metadata_attempts+1,metadata_revision=?,metadata_updated_at=?
           WHERE kp_id=?""",
        (
            metadata["title"], metadata["original_title"], metadata["year"], metadata["release_date"],
            metadata["description"], metadata["runtime_minutes"], metadata["kp_rating"],
            metadata["kp_vote_count"], metadata["imdb_id"], metadata["imdb_rating"],
            origin.get("code"), origin.get("label"), origin.get("confidence", 0.0),
            origin.get("method", "not_detected"), origin_evidence, now,
            now, METADATA_REVISION, now, media["kp_id"],
        ),
    )
    metadata = dict(metadata, origin_platform=origin)
    replace_features(connection, media["kp_id"], metadata)
    if media["media_type"] == "tv":
        state = series_state(metadata)
        for profile in connection.execute("SELECT profile_id FROM user_ratings WHERE kp_id=?", (media["kp_id"],)):
            save_series_tracking(connection, profile[0], media["kp_id"], state)


def calculate_feature_stats(connection, profile_id):
    now = int(time.time())
    connection.execute(
        "DELETE FROM profile_feature_stats WHERE profile_id=? AND formula_version=?",
        (profile_id, FORMULA_VERSION),
    )
    rows = connection.execute(
        """SELECT f.feature_id,f.feature_type,COUNT(*) sample_count,SUM(mf.weight) effective_count,
                  SUM(ur.rating*mf.weight)/SUM(mf.weight) mean_rating,
                  SUM(rs.utility*mf.weight)/SUM(mf.weight) mean_utility,
                  SUM(CASE WHEN ur.rating>=6 THEN mf.weight ELSE 0 END)/SUM(mf.weight) positive_rate,
                  SUM(CASE WHEN ur.rating<=4 THEN mf.weight ELSE 0 END)/SUM(mf.weight) negative_rate
           FROM user_ratings ur
           JOIN rating_scale rs ON rs.profile_id=ur.profile_id AND rs.rating=ur.rating
           JOIN media_features mf ON mf.kp_id=ur.kp_id
           JOIN features f ON f.feature_id=mf.feature_id
           WHERE ur.profile_id=? GROUP BY f.feature_id,f.feature_type""",
        (profile_id,),
    ).fetchall()
    for row in rows:
        effective = float(row["effective_count"])
        confidence = effective / (effective + FEATURE_K.get(row["feature_type"], 10.0))
        affinity = max(0.35, min(1.80, 1 + 0.65 * row["mean_utility"] * confidence))
        connection.execute(
            """INSERT INTO profile_feature_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                profile_id, row["feature_id"], row["sample_count"], effective, row["mean_rating"],
                row["mean_utility"], row["positive_rate"], row["negative_rate"], 1.0,
                confidence, affinity, now, FORMULA_VERSION,
            ),
        )


def feature_report(connection, profile_id, positive, limit=25):
    direction = "DESC" if positive else "ASC"
    rows = connection.execute(
        f"""SELECT f.feature_type,f.name,p.sample_count,p.mean_rating,p.mean_utility,
                   p.confidence,p.affinity_multiplier
            FROM profile_feature_stats p JOIN features f USING(feature_id)
            WHERE p.profile_id=? AND p.formula_version=? AND p.sample_count>=3
            ORDER BY p.affinity_multiplier {direction},p.sample_count DESC LIMIT ?""",
        (profile_id, FORMULA_VERSION, limit),
    ).fetchall()
    result = []
    for row in rows:
        examples = connection.execute(
            """SELECT m.title,ur.rating FROM features f JOIN media_features mf USING(feature_id)
               JOIN media m USING(kp_id) JOIN user_ratings ur USING(kp_id)
               WHERE f.feature_type=? AND f.name=? AND ur.profile_id=?
               ORDER BY ur.rating DESC,m.kp_vote_count DESC LIMIT 4""",
            (row["feature_type"], row["name"], profile_id),
        ).fetchall()
        item = dict(row)
        item["examples"] = [{"title": item[0], "rating": item[1]} for item in examples]
        result.append(item)
    return result


def origin_platform_report(connection):
    result = []
    rows = connection.execute(
        """SELECT origin_platform,origin_platform_label,COUNT(*) count,
                  AVG(origin_platform_confidence) average_confidence
           FROM media WHERE origin_platform IS NOT NULL
           GROUP BY origin_platform,origin_platform_label
           ORDER BY count DESC,origin_platform_label"""
    ).fetchall()
    for row in rows:
        examples = [dict(item) for item in connection.execute(
            """SELECT kp_id,title,release_year,media_type,origin_platform_confidence,
                      origin_platform_method,origin_platform_evidence
               FROM media WHERE origin_platform=?
               ORDER BY origin_platform_confidence DESC,kp_vote_count DESC,title LIMIT 8""",
            (row["origin_platform"],),
        )]
        result.append({
            "code": row["origin_platform"],
            "label": row["origin_platform_label"],
            "count": row["count"],
            "average_confidence": row["average_confidence"],
            "examples": examples,
        })
    return result


def build_report(connection):
    metadata_counts = {
        row[0]: row[1]
        for row in connection.execute("SELECT metadata_status,COUNT(*) FROM media GROUP BY metadata_status")
    }
    profiles = []
    for profile in connection.execute("SELECT profile_id,display_name FROM profiles ORDER BY profile_id"):
        profile_id = profile["profile_id"]
        states = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT airing_state,COUNT(*) FROM series_tracking WHERE profile_id=? GROUP BY airing_state",
                (profile_id,),
            )
        }
        airing = [dict(row) for row in connection.execute(
            """SELECT m.kp_id,m.title,ur.rating,st.current_season,st.last_episode_number,
                      st.last_air_date,st.next_episode_number,st.next_air_date,st.state_reason
               FROM series_tracking st JOIN media m USING(kp_id)
               JOIN user_ratings ur ON ur.profile_id=st.profile_id AND ur.kp_id=st.kp_id
               WHERE st.profile_id=? AND st.airing_state='airing' AND st.tracking_mode!='muted'
               ORDER BY COALESCE(st.next_air_date,'9999-12-31'),m.title""",
            (profile_id,),
        )]
        profiles.append({
            "profile_id": profile_id,
            "display_name": profile["display_name"],
            "rating_distribution": {
                str(row[0]): row[1] for row in connection.execute(
                    "SELECT rating,COUNT(*) FROM user_ratings WHERE profile_id=? GROUP BY rating ORDER BY rating",
                    (profile_id,),
                )
            },
            "positive_features": feature_report(connection, profile_id, True),
            "negative_features": feature_report(connection, profile_id, False),
            "series_states": states,
            "airing_now": airing,
        })
    errors = [dict(row) for row in connection.execute(
        """SELECT kp_id,title,metadata_attempts,metadata_error FROM media
           WHERE metadata_status='error' ORDER BY metadata_attempts DESC,kp_id LIMIT 100"""
    )]
    return {
        "generated_at": int(time.time()),
        "formula_version": FORMULA_VERSION,
        "stage": "calibration_only",
        "recommendations_enabled": False,
        "source": "kinopoisk",
        "metadata": {
            "ready": metadata_counts.get("ready", 0),
            "pending": metadata_counts.get("pending", 0),
            "error": metadata_counts.get("error", 0),
        },
        "origin_platforms": origin_platform_report(connection),
        "errors": errors,
        "profiles": profiles,
        "notes": [
            "Кинопоиск является единственным источником каталожных метаданных.",
            "Оценка 5 нейтральна; 6 и 7 дают положительный, но умеренный сигнал.",
            "Тема извлекается локально из описания по версионируемому словарю.",
            "Сериал без подтверждённой даты серии не попадает в «Сейчас выходят».",
        ],
    }


def report_markdown(report):
    meta = report["metadata"]
    lines = [
        "# Калибровочный отчёт рекомендателя", "",
        f"Сформирован: {datetime.fromtimestamp(report['generated_at'], timezone.utc).isoformat()}", "",
        "Источник метаданных: **Кинопоиск**. Рекомендации в Lampa пока **не включены**.", "",
        "## Обогащение", "",
        "| Готово | Ожидают | Ошибки |", "|---:|---:|---:|",
        f"| {meta['ready']} | {meta['pending']} | {meta['error']} |",
    ]
    lines += ["", "## Платформы и телеканалы", "",
              "| Платформа | Найдено | Средняя уверенность | Примеры |",
              "|---|---:|---:|---|"]
    for platform in report.get("origin_platforms", []):
        examples = ", ".join(item["title"] for item in platform["examples"][:5])
        lines.append(
            f"| {platform['label']} | {platform['count']} | "
            f"{platform['average_confidence']:.2f} | {examples} |"
        )
    for profile in report["profiles"]:
        lines += ["", f"## Профиль {profile['display_name']}", "", "### Положительные признаки", "",
                  "| Тип | Признак | N | Средняя оценка | Множитель | Примеры |",
                  "|---|---|---:|---:|---:|---|"]
        for item in profile["positive_features"][:15]:
            examples = ", ".join(f"{example['title']} ({example['rating']})" for example in item["examples"])
            lines.append(
                f"| {item['feature_type']} | {item['name']} | {item['sample_count']} | "
                f"{item['mean_rating']:.2f} | {item['affinity_multiplier']:.3f} | {examples} |"
            )
        lines += ["", "### Отрицательные признаки", "",
                  "| Тип | Признак | N | Средняя оценка | Множитель | Примеры |",
                  "|---|---|---:|---:|---:|---|"]
        for item in profile["negative_features"][:15]:
            examples = ", ".join(f"{example['title']} ({example['rating']})" for example in item["examples"])
            lines.append(
                f"| {item['feature_type']} | {item['name']} | {item['sample_count']} | "
                f"{item['mean_rating']:.2f} | {item['affinity_multiplier']:.3f} | {examples} |"
            )
        lines += ["", "### Сейчас выходят", ""]
        if profile["airing_now"]:
            lines += ["| Сериал | Моя оценка | Сезон | Последняя серия | Следующая серия |",
                      "|---|---:|---:|---|---|"]
            for item in profile["airing_now"]:
                last = f"E{item['last_episode_number']} · {item['last_air_date']}" if item["last_episode_number"] else "—"
                upcoming = f"E{item['next_episode_number']} · {item['next_air_date']}" if item["next_episode_number"] else "—"
                lines.append(f"| {item['title']} | {item['rating']} | {item['current_season'] or '—'} | {last} | {upcoming} |")
        else:
            lines.append("Пока нет сериалов с подтверждённым активным окном выхода.")
    lines += ["", "## Оговорки", ""] + [f"- {note}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


def write_reports(connection):
    report = build_report(connection)
    for path, content in (
        (REPORT_JSON_FILE, json.dumps(report, ensure_ascii=False, indent=2)),
        (REPORT_MD_FILE, report_markdown(report)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)


def snapshot_database(reason="startup"):
    if not DB_FILE.exists():
        return None
    DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = DB_BACKUP_DIR / f"recommender-{stamp}-{reason}.sqlite3"
    source = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True, timeout=60)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    backups = sorted(DB_BACKUP_DIR.glob("recommender-*.sqlite3"), reverse=True)
    for old in backups[5:]:
        old.unlink()
    print(f"database snapshot: {target}", flush=True)
    return target


def refresh_candidates_if_due():
    if not CANDIDATE_ENABLED:
        return []
    connection = open_database()
    try:
        row = connection.execute(
            "SELECT value FROM sync_state WHERE key='candidate_catalog_last_sync'"
        ).fetchone()
        last_sync = int(row[0]) if row and str(row[0]).isdigit() else 0
        if last_sync and time.time() - last_sync < CANDIDATE_REFRESH_SECONDS:
            return []
        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory) / "cookies.txt"
            establish_session(cookie_file)
            def fetch_candidate_page(url):
                KINOPOISK_METADATA_LIMITER.wait()
                return curl(url, cookie_file, False)
            summary = refresh_candidate_catalog(
                connection,
                fetch_candidate_page,
                pages=CANDIDATE_PAGES,
            )
        now = int(time.time())
        failed = any(item.get("status") != "updated" for item in summary)
        next_marker = now - CANDIDATE_REFRESH_SECONDS + 3600 if failed else now
        with connection:
            connection.execute(
                """INSERT INTO sync_state(key,value,updated_at)
                   VALUES('candidate_catalog_last_sync',?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                (str(next_marker), now),
            )
        print(f"candidate catalog: {json.dumps(summary, ensure_ascii=False)}", flush=True)
        for profile in connection.execute("SELECT profile_id FROM profiles"):
            report = write_recommendation_reports(
                connection,
                profile[0],
                RECOMMENDATIONS_JSON_FILE,
                RECOMMENDATIONS_MD_FILE,
                50,
            )
            print(
                f"recommendation report: ready={report['catalog']['ready']} "
                f"remaining={report['catalog']['remaining']} scored={report['scored_count']}",
                flush=True,
            )
        return summary
    finally:
        connection.close()


def run_enrichment():
    connection = open_database()
    started = int(time.time())
    stale_movie = started - METADATA_MAX_AGE
    stale_series = started - SERIES_METADATA_MAX_AGE
    rows = connection.execute(
        """SELECT * FROM media
           WHERE metadata_status='pending'
              OR (metadata_status='error' AND COALESCE(metadata_updated_at,0)<?)
              OR (metadata_status='ready' AND COALESCE(metadata_updated_at,0)<
                  CASE WHEN media_type='tv' THEN ? ELSE ? END)
           ORDER BY CASE metadata_status WHEN 'pending' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
                    CASE WHEN kp_id IN (SELECT kp_id FROM user_ratings) THEN 0 ELSE 1 END,
                    kp_vote_count DESC
           LIMIT ?""",
        (started - 6 * 3600, stale_series, stale_movie, ENRICH_BATCH_SIZE),
    ).fetchall()
    run_id = connection.execute(
        "INSERT INTO metadata_runs(started_at,status,selected_count) VALUES(?,'running',?)",
        (started, len(rows)),
    ).lastrowid
    connection.commit()
    processed = ready = errors = 0
    details = []
    try:
        if rows:
            with tempfile.TemporaryDirectory() as directory:
                cookie_file = Path(directory) / "cookies.txt"
                establish_session(cookie_file)
                def fetch_one(media):
                    return media, fetch_metadata_with_cookie(
                        media["kp_id"], media["media_type"], cookie_file, False
                    )

                with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as pool:
                    futures = {pool.submit(fetch_one, media): media for media in rows}
                    for future in as_completed(futures):
                        media = futures[future]
                        try:
                            _, metadata = future.result()
                            persist_metadata(connection, media, metadata)
                            ready += 1
                        except Exception as error:
                            errors += 1
                            message = str(error)[:500]
                            details.append({"kp_id": media["kp_id"], "error": message})
                            connection.execute(
                                """UPDATE media SET metadata_status='error',metadata_error=?,
                                          metadata_attempts=metadata_attempts+1,metadata_updated_at=?
                                   WHERE kp_id=?""",
                                (message, int(time.time()), media["kp_id"]),
                            )
                        processed += 1
                        connection.execute(
                            """UPDATE metadata_runs SET processed_count=?,ready_count=?,error_count=?,details_json=?
                               WHERE run_id=?""",
                            (processed, ready, errors, json.dumps({"errors": details[-20:]}, ensure_ascii=False), run_id),
                        )
                        connection.commit()
                        if processed == 1 or processed % 10 == 0 or processed == len(rows):
                            print(
                                f"kinopoisk metadata: {processed}/{len(rows)} ready={ready} "
                                f"errors={errors} workers={ENRICH_WORKERS}",
                                flush=True,
                            )
        for profile in connection.execute("SELECT profile_id FROM profiles"):
            calculate_feature_stats(connection, profile[0])
            write_recommendation_reports(
                connection,
                profile[0],
                RECOMMENDATIONS_JSON_FILE,
                RECOMMENDATIONS_MD_FILE,
                50,
            )
        write_reports(connection)
        status = "completed_with_errors" if errors else "completed"
        connection.execute(
            """UPDATE metadata_runs SET finished_at=?,status=?,processed_count=?,ready_count=?,
                      error_count=?,details_json=? WHERE run_id=?""",
            (
                int(time.time()), status, processed, ready, errors,
                json.dumps({"errors": details}, ensure_ascii=False), run_id,
            ),
        )
        connection.commit()
        pending = connection.execute("SELECT COUNT(*) FROM media WHERE metadata_status='pending'").fetchone()[0]
        print(f"kinopoisk batch finished: ready={ready} errors={errors} pending={pending}", flush=True)
        return {"more_work": pending > 0, "blocked": bool(processed and errors == processed)}
    except Exception as error:
        connection.execute(
            "UPDATE metadata_runs SET finished_at=?,status='failed',details_json=? WHERE run_id=?",
            (int(time.time()), json.dumps({"error": str(error)}, ensure_ascii=False), run_id),
        )
        connection.commit()
        raise
    finally:
        connection.close()


def import_connected_profile(profile):
    data = sync(profile)
    persist_database(data)
    if profile == PROFILE_ID:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = DATA_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(DATA_FILE)
    return data


def refresh_file():
    from connections import IMPORT_LOCK, ensure
    with IMPORT_LOCK:
        data = import_connected_profile(PROFILE_ID)
        connection = direct_connection()
        try:
            ensure(connection)
            others = [r[0] for r in connection.execute("SELECT profile_id FROM home_connections WHERE profile_id<>?", (PROFILE_ID,))]
        finally:
            connection.close()
        for profile in others:
            try:
                import_connected_profile(profile)
            except Exception:
                print("Connected profile import failed; saved ratings retained", flush=True)
    print(f"updated: ratings={data['ratings_count']} watchlist={data['watchlist_count']}", flush=True)


def refresh_loop():
    while True:
        try:
            refresh_file()
        except Exception as error:
            print(f"update failed: {error}", flush=True)
        time.sleep(REFRESH_SECONDS)


def enrichment_loop():
    while not DATA_FILE.exists():
        time.sleep(2)
    while True:
        try:
            refresh_candidates_if_due()
            result = run_enrichment()
        except Exception as error:
            print(f"enrichment failed: {error}", flush=True)
            time.sleep(ENRICH_SECONDS)
            continue
        time.sleep(
            ENRICH_CONTINUE_DELAY_SECONDS
            if result["more_work"] and not result["blocked"]
            else ENRICH_SECONDS
        )


def direct_connection():
    connection = sqlite3.connect(DB_FILE, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def card_year(params):
    return _int_or_none((params.get("year") or [""])[0])


def find_card_in_database(connection, params):
    kp_id = _int_or_none((params.get("kp_id") or [""])[0])
    if kp_id:
        return connection.execute("SELECT * FROM media WHERE kp_id=?", (kp_id,)).fetchone()
    imdb_id = normalized_text((params.get("imdb_id") or [""])[0])
    if imdb_id:
        row = connection.execute("SELECT * FROM media WHERE imdb_id=?", (imdb_id,)).fetchone()
        if row:
            return row
    title = normalized_key((params.get("title") or [""])[0])
    original = normalized_key((params.get("original_title") or [""])[0])
    year = card_year(params)
    media_type = "tv" if (params.get("type") or [""])[0] == "tv" else "movie"
    rows = connection.execute(
        "SELECT * FROM media WHERE media_type=? AND (? IS NULL OR release_year=?)",
        (media_type, year, year),
    ).fetchall()
    for row in rows:
        names = {normalized_key(row["title"]), normalized_key(row["original_title"])} - {""}
        if title in names or original in names:
            return row
    return None


def lampac_external_ids(params):
    tmdb_id = _int_or_none((params.get("tmdb_id") or [""])[0])
    if not tmdb_id:
        return {}
    serial = 1 if (params.get("type") or [""])[0] == "tv" else 0
    url = f"{LAMPAC_URL}/externalids?{urlencode({'id': tmdb_id, 'serial': serial})}"
    process = subprocess.run(
        ["curl", "-fsS", "--connect-timeout", "3", "--max-time", "12", url],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(process.stdout.decode("utf-8", "replace"))


def fetch_metadata_with_cookie(kp_id, media_type, cookie_file, interactive=False):
    previous = getattr(REQUEST_CONTEXT, "metadata", False)
    REQUEST_CONTEXT.metadata = True
    try:
        route = "series" if media_type == "tv" else "film"
        page = curl(f"https://www.kinopoisk.ru/{route}/{kp_id}/", cookie_file, False)
        metadata = parse_kinopoisk_page(page, kp_id, media_type)
        supplement_kinopoisk_ratings(metadata, cookie_file)
        if interactive:
            metadata["_interactive"] = True
        supplement_origin_platform(metadata)
        return metadata
    finally:
        REQUEST_CONTEXT.metadata = previous


def fetch_card_metadata(kp_id, media_type):
    with tempfile.TemporaryDirectory() as directory:
        cookie_file = Path(directory) / "cookies.txt"
        cookie_file.touch()
        return fetch_metadata_with_cookie(kp_id, media_type, cookie_file, True)


def card_needs_refresh(row):
    return bool(
        row["metadata_status"] != "ready"
        or int(row["metadata_revision"] or 0) < METADATA_REVISION
        or not row["kp_rating"]
        or not row["imdb_rating"]
        or not row["origin_platform_checked_at"]
        or (not row["origin_platform"] and time.time() - float(row["origin_platform_checked_at"] or 0) > 86400)
    )


def schedule_card_refresh(kp_id, media_type):
    with CARD_REFRESH_LOCK:
        if kp_id in CARD_REFRESHING:
            return
        CARD_REFRESHING.add(kp_id)

    def refresh():
        try:
            metadata = fetch_card_metadata(kp_id, media_type)
            connection = direct_connection()
            try:
                row = connection.execute("SELECT * FROM media WHERE kp_id=?", (kp_id,)).fetchone()
                if row:
                    persist_metadata(connection, row, metadata)
                    connection.commit()
                    print(f"card metadata refreshed: kp_id={kp_id}", flush=True)
            finally:
                connection.close()
        except Exception as error:
            print(f"card metadata refresh failed: kp_id={kp_id} error={str(error)[:300]}", flush=True)
        finally:
            with CARD_REFRESH_LOCK:
                CARD_REFRESHING.discard(kp_id)

    threading.Thread(target=refresh, daemon=True).start()


def card_ratings(params, profile_id=None):
    profile_id = PROFILE_ID if profile_id is None else profile_id
    with CARD_LOOKUP_LOCK:
        connection = direct_connection()
        try:
            row = find_card_in_database(connection, params)
            external = {}
            cached_only = (params.get("cached") or [""])[0] == "1"
            if not row and not cached_only:
                try:
                    external = lampac_external_ids(params)
                except Exception:
                    external = {}
                kp_id = _int_or_none(external.get("kinopoisk_id"))
                if kp_id:
                    row = connection.execute("SELECT * FROM media WHERE kp_id=?", (kp_id,)).fetchone()
                    if not row:
                        media_type = "tv" if (params.get("type") or [""])[0] == "tv" else "movie"
                        title = normalized_text((params.get("title") or [""])[0]) or f"KP {kp_id}"
                        year = card_year(params)
                        connection.execute(
                            "INSERT OR IGNORE INTO media(kp_id,media_type,title,release_year,tmdb_id,imdb_id) VALUES(?,?,?,?,?,?)",
                            (
                                kp_id, media_type, title, year,
                                _int_or_none((params.get("tmdb_id") or [""])[0]),
                                external.get("imdb_id") or None,
                            ),
                        )
                        connection.commit()
                        row = connection.execute("SELECT * FROM media WHERE kp_id=?", (kp_id,)).fetchone()
            if not row:
                return {"found": False}
            corrections_path = APP_DIR / 'platform_corrections.json'
            corrections = json.loads(corrections_path.read_text(encoding='utf-8')) if corrections_path.exists() else []
            for correction in ([] if cached_only else corrections):
                if (row['media_type'] == correction['media_type'] and row['release_year'] == correction['release_year']
                        and normalized_key(row['original_title']) == normalized_key(correction['original_title'])):
                    connection.execute('''UPDATE media SET origin_platform=?,origin_platform_label=?,
                        origin_platform_confidence=1,origin_platform_method='verified_correction',
                        origin_platform_evidence=?,origin_platform_checked_at=? WHERE kp_id=?''',
                        (correction['platform'],correction['label'],correction['source'],int(time.time()),row['kp_id']))
                    connection.commit()
                    row=connection.execute('SELECT * FROM media WHERE kp_id=?',(row['kp_id'],)).fetchone()
            needs_refresh = card_needs_refresh(row)
            force_refresh = (params.get("refresh") or [""])[0] in ("1", "true", "yes")
            if needs_refresh and force_refresh and not cached_only:
                metadata = fetch_card_metadata(row["kp_id"], row["media_type"])
                persist_metadata(connection, row, metadata)
                connection.commit()
                row = connection.execute("SELECT * FROM media WHERE kp_id=?", (row["kp_id"],)).fetchone()
                needs_refresh = False
            elif needs_refresh and not cached_only:
                schedule_card_refresh(row["kp_id"], row["media_type"])
            own = connection.execute(
                "SELECT rating FROM user_ratings WHERE profile_id=? AND kp_id=?",
                (profile_id, row["kp_id"]),
            ).fetchone()
            from candidate_engine import predict_card
            prediction = None
            if not own and row['metadata_status'] == 'ready':
                if cached_only:
                    score = connection.execute('SELECT predicted_rating FROM candidate_scores WHERE profile_id=? AND kp_id=? ORDER BY formula_version DESC LIMIT 1', (profile_id, row['kp_id'])).fetchone()
                    prediction = score[0] if score else predict_card(connection, profile_id, row['kp_id'], row['kp_rating'])
                else:
                    prediction = predict_card(connection, profile_id, row['kp_id'], row['kp_rating'])
            return {
                "found": True,
                "kp_id": row["kp_id"],
                "kp_rating": row["kp_rating"],
                "imdb_rating": row["imdb_rating"],
                "my_rating": own[0] if own else None,
                "predicted_rating": prediction,
                "prediction_stage": "preliminary" if prediction is not None else "insufficient_data",
                "origin_platform": row["origin_platform"],
                "origin_platform_label": row["origin_platform_label"],
                "origin_platform_confidence": row["origin_platform_confidence"],
                "refresh_pending": needs_refresh,
            }
        finally:
            connection.close()


HOME_CACHE = None


def rated_airing_series(connection, profile_id, today=None):
    """A rating is evidence of interest, not a fabricated playback position."""
    from datetime import date, timedelta
    from review_api import hidden_home_ids
    hidden=set(hidden_home_ids(connection,profile_id))
    today=today or date.today()
    lower=(today-timedelta(days=ACTIVE_RECENT_DAYS)).isoformat()
    upper=(today+timedelta(days=ACTIVE_NEXT_DAYS)).isoformat()
    return [dict(row) for row in connection.execute("""
        SELECT m.kp_id,m.title,m.release_year,m.media_type,ur.rating my_rating,
               st.next_air_date,st.last_air_date,st.state_reason,
               'rated_airing' continue_reason
        FROM series_tracking st JOIN media m USING(kp_id)
        JOIN user_ratings ur ON ur.kp_id=st.kp_id AND ur.profile_id=st.profile_id
        WHERE st.profile_id=? AND st.tracking_mode!='muted' AND st.airing_state='airing'
          AND m.media_type='tv' AND st.active_from IS NOT NULL AND st.active_from<=?
          AND ((st.next_air_date BETWEEN ? AND ?) OR (st.last_air_date BETWEEN ? AND ?))
        ORDER BY COALESCE(st.next_air_date,st.last_air_date) DESC,m.kp_id
        """,(profile_id,today.isoformat(),lower,upper,lower,today.isoformat())) if str(row["kp_id"]) not in hidden]


def home_personal_data():
    from home_cache import kinopoisk_enabled
    if not kinopoisk_enabled():
        return [], [], []
    from review_api import review_data
    connection = direct_connection()
    try:
        report = json.loads(RECOMMENDATIONS_JSON_FILE.read_text(encoding="utf-8")) if RECOMMENDATIONS_JSON_FILE.exists() else {}
        from candidate_engine import RECOMMENDATION_FORMULA_VERSION
        if report.get('formula_version') != RECOMMENDATION_FORMULA_VERSION:
            report=write_recommendation_reports(connection,PROFILE_ID,
                RECOMMENDATIONS_JSON_FILE,RECOMMENDATIONS_MD_FILE,50)
        items = review_data(connection, PROFILE_ID, report)["items"]
        if not DATA_FILE.exists():
            raise ValueError("Kinopoisk profile not ready")
        watch = json.loads(DATA_FILE.read_text(encoding="utf-8")).get("watchlist", [])
        from episode_schedule import refresh
        from home_cache import config
        schedule_cookie=DATA_FILE.parent / 'episode-cookies.txt'
        schedule_session=[False]
        schedule_lock=threading.Lock()
        def fetch_schedule(url):
            with schedule_lock:
                if not schedule_session[0]:
                    establish_session(schedule_cookie)
                    schedule_session[0]=True
            KINOPOISK_METADATA_LIMITER.wait()
            process=subprocess.run(['curl','-fsSL','--compressed','--connect-timeout','3',
                '--max-time','8','-A',UA,'-b',str(schedule_cookie),
                '-b','sso_status=sso.passport.yandex.ru:synchronized',url],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            return process.stdout.decode('utf-8','replace')
        pending_schedules=refresh(connection,fetch_schedule,series_state,save_series_tracking,
            PROFILE_ID,config().get('episode_priority_ids',[]))
        airing=rated_airing_series(connection,PROFILE_ID)
        context = {
            'rated': [r[0] for r in connection.execute(
                'SELECT kp_id FROM user_ratings WHERE profile_id=?', (PROFILE_ID,))],
            'airing': [r['kp_id'] for r in airing],
            'ended': [r[0] for r in connection.execute(
                "SELECT kp_id FROM series_tracking WHERE profile_id=? AND airing_state IN ('ended','canceled')", (PROFILE_ID,))],
            'seen': [r[0] for r in connection.execute(
                "SELECT kp_id FROM recommendation_feedback WHERE profile_id=? AND status IN ('seen','not_interested')", (PROFILE_ID,))],
        }
        # Use exactly the saved model used by cached card badges, no network.
        from candidate_engine import predict_card
        context['card_predictions']={}
        if HOME_CACHE:
            for shelf in HOME_CACHE.snapshot('*')['rows']:
                if shelf['kind'] not in ('fire','now'): continue
                for card in shelf['results']:
                    kp=card.get('kinopoisk_id')
                    if not str(kp or '').isdigit() or int(kp) in context['rated']: continue
                    row=connection.execute("SELECT kp_id,kp_rating,media_type FROM media WHERE kp_id=? AND metadata_status='ready'",(int(kp),)).fetchone()
                    if not row: continue
                    prediction=predict_card(connection,PROFILE_ID,row['kp_id'],row['kp_rating'])
                    if prediction is not None:
                        context['card_predictions'][str(kp)]={'kp_id':int(kp),'media_type':row['media_type'],
                            'predicted_rating':prediction,'prediction_stage':'preliminary'}
        return items, watch, airing, pending_schedules, context
    finally:
        connection.close()


CLIENT_DIAGNOSTICS = []
CLIENT_DIAGNOSTICS_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def review_response(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.review_response(200, {})

    def route_profile(self):
        parsed = urlparse(self.path)
        match = re.fullmatch(r'/p/([A-Za-z0-9_-]{1,80})(/.*)', parsed.path)
        if not match:
            return PROFILE_ID
        profile = match[1]
        connection = direct_connection()
        try:
            if not connection.execute('SELECT 1 FROM profiles WHERE profile_id=?', (profile,)).fetchone():
                raise ValueError('Unknown profile')
        finally:
            connection.close()
        self.path = match[2] + ('?' + parsed.query if parsed.query else '')
        return profile

    def prepare_profile(self):
        try:
            return self.route_profile()
        except ValueError as error:
            self.review_response(404, {'error': str(error)})
            return None

    def cloud_request(self):
        from cloud_disk import handle
        return handle(self, direct_connection, PROFILE_ID, DATA_FILE.parent / 'cloud')

    def connected_services(self):
        if urlparse(self.path).path != '/connections.json':
            return False
        from connections import read, ensure, kp_id, start_import
        from cloud_disk import allowed_origin
        if not allowed_origin(self):
            self.review_response(403, {'error': 'Откройте настройки из HomeCinema'})
            return True
        connection = direct_connection()
        try:
            if self.command == 'GET':
                profile = parse_qs(urlparse(self.path).query).get('id', [PROFILE_ID])[0]
                if not connection.execute('SELECT 1 FROM profiles WHERE profile_id=?', (profile,)).fetchone():
                    raise ValueError('Неизвестный профиль')
                self.review_response(200, read(connection, profile, PROFILE_ID))
            else:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Ожидается JSON')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('Недопустимый размер запроса')
                payload = json.loads(self.rfile.read(length))
                profile = payload.get('profile_id')
                value = kp_id(payload.get('kp_id'))
                if not connection.execute('SELECT 1 FROM profiles WHERE profile_id=?', (profile,)).fetchone():
                    raise ValueError('Неизвестный профиль')
                ensure(connection)
                with connection:
                    connection.execute('INSERT INTO home_connections(profile_id,kp_id) VALUES(?,?) '
                        'ON CONFLICT(profile_id) DO UPDATE SET kp_id=excluded.kp_id,error=""', (profile, value))
                start_import(direct_connection, profile, import_connected_profile)
                self.review_response(200, {'ok': True, 'kp_id': value, 'queued': True})
        except (ValueError, TypeError):
            self.review_response(400, {'error': 'Проверьте ID/ссылку Кинопоиска и выбранный профиль'})
        finally:
            connection.close()
        return True

    def do_POST(self):
        if self.cloud_request() or self.connected_services():
            return
        from profiles import handle
        if handle(self, direct_connection, PROFILE_ID, PROFILE_DISPLAY_NAME):
            return
        profile_id = self.prepare_profile()
        if profile_id is None:
            return
        path = urlparse(self.path).path
        if path not in ("/review-feedback.json", "/track-preferences.json", "/client-diagnostics.json"):
            self.review_response(404, {"error": "Not found"})
            return
        from review_api import save_feedback
        connection = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid body size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected object")
            if path == "/client-diagnostics.json":
                event = {key: str(payload.get(key, ""))[:1800] for key in ("version", "stage", "message", "agent")}
                event["received_at"] = int(time.time())
                with CLIENT_DIAGNOSTICS_LOCK:
                    CLIENT_DIAGNOSTICS.append(event)
                    del CLIENT_DIAGNOSTICS[:-100]
                print("client diagnostic: " + json.dumps(event, ensure_ascii=False), flush=True)
                self.review_response(200, {"ok": True})
                return
            connection = direct_connection()
            if path == "/track-preferences.json":
                from track_preferences import save
                result = save(connection, profile_id, payload)
            else:
                result = save_feedback(connection, profile_id, payload)
            self.review_response(200, result)
        except (ValueError, TypeError) as error:
            self.review_response(400, {"error": str(error)})
        except Exception as error:
            print(f"review save failed: {error}", flush=True)
            self.review_response(503, {"error": "Cannot save feedback; retry"})
        finally:
            if connection is not None:
                connection.close()

    def do_GET(self):
        if self.cloud_request() or self.connected_services():
            return
        from profiles import handle
        if handle(self, direct_connection, PROFILE_ID, PROFILE_DISPLAY_NAME):
            return
        profile_id = self.prepare_profile()
        if profile_id is None:
            return
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if re.fullmatch(r'/facts/kp/[1-9][0-9]{0,9}\.json', path):
            from facts import get_facts
            try:
                kp_id=path.rsplit('/',1)[1][:-5]
                media_type=parse_qs(parsed_url.query).get('type',['movie'])[0]
                self.review_response(200,get_facts(DATA_FILE.parent/'facts',kp_id,media_type))
            except ValueError as error:
                self.review_response(400,{'error':str(error),'items':[]})
            except Exception:
                self.review_response(503,{'error':'Факты временно недоступны','items':[]})
            return
        if path == '/notifications.json':
            connection = direct_connection()
            try:
                from profiles import notices
                self.review_response(200, notices(connection, profile_id, HOME_CACHE))
            except Exception:
                self.review_response(200, {'items': []})
            finally:
                connection.close()
            return
        if path == '/data.json' and profile_id != PROFILE_ID:
            connection = direct_connection()
            try:
                from profiles import catalog_data
                self.review_response(200, catalog_data(connection, profile_id))
            finally:
                connection.close()
            return
        if profile_id != PROFILE_ID and path in ('/report.json', '/report.md', '/recommendations.json', '/recommendations.md', '/airing.json'):
            self.review_response(200, {'profile_id': profile_id, 'groups': [], 'items': []})
            return
        if path == "/prediction-calibration.json":
            connection=direct_connection()
            try:
                from candidate_engine import stored_rating_model
                self.review_response(200,stored_rating_model(connection,profile_id) or {'ready':False})
            finally:
                connection.close()
            return
        if path == "/review-cached.json":
            revision=parse_qs(parsed_url.query).get('revision',[''])[0]
            self.review_response(200,HOME_CACHE.review_snapshot(profile_id,revision) if HOME_CACHE else
                {'profile_id':profile_id,'items':[],'revision':'','warming':True})
            return
        if path == "/home.json":
            # Read-only: never trigger fetching, scoring or cache rebuilding here.
            from review_api import home_snapshot
            connection=direct_connection()
            try:
                self.review_response(200, home_snapshot(connection, HOME_CACHE, profile_id))
            finally:
                connection.close()
            return
        if path == "/client-diagnostics.json":
            with CLIENT_DIAGNOSTICS_LOCK:
                events = list(CLIENT_DIAGNOSTICS)
            self.review_response(200, {"events": events})
            return
        if path == "/track-preferences.json":
            from track_preferences import read
            connection = None
            try:
                connection = direct_connection()
                series = parse_qs(parsed_url.query).get('series_key', [''])[0]
                self.review_response(200, read(connection, profile_id, series))
            except ValueError as error:
                self.review_response(400, {"error": str(error)})
            except Exception as error:
                print(f"track preferences: {error}", flush=True)
                self.review_response(503, {"error": "Preferences unavailable"})
            finally:
                if connection is not None:
                    connection.close()
            return
        if path == "/review.json" and profile_id != PROFILE_ID:
            connection = direct_connection()
            try:
                from review_api import review_data
                self.review_response(200, review_data(connection, profile_id, {}))
            finally:
                connection.close()
            return
        if path == "/review.json":
            from review_api import review_data
            connection = None
            try:
                connection = direct_connection()
                if RECOMMENDATIONS_JSON_FILE.exists():
                    report = json.loads(RECOMMENDATIONS_JSON_FILE.read_text(encoding="utf-8"))
                    from candidate_engine import RECOMMENDATION_FORMULA_VERSION
                    if report.get('formula_version') and report['formula_version'] != RECOMMENDATION_FORMULA_VERSION:
                        report = write_recommendation_reports(connection, profile_id,
                            RECOMMENDATIONS_JSON_FILE, RECOMMENDATIONS_MD_FILE, 50)
                else:
                    report = write_recommendation_reports(connection, profile_id,
                        RECOMMENDATIONS_JSON_FILE, RECOMMENDATIONS_MD_FILE, 50)
                self.review_response(200, review_data(connection, profile_id, report))
            except Exception as error:
                print(f"review read failed: {error}", flush=True)
                self.review_response(503, {"error": "Review is not ready yet"})
            finally:
                if connection is not None:
                    connection.close()
            return
        if path not in ("/data.json", "/health", "/kinopoisk.js", "/report.json", "/report.md", "/airing.json", "/platforms.json", "/recommendations.json", "/recommendations.md", "/card-ratings.json"):
            self.send_error(404)
            return
        try:
            if path == "/health":
                raw = json.dumps({
                    "ok": DATA_FILE.exists(),
                    "database": DB_FILE.exists(),
                    "calibration_report": REPORT_JSON_FILE.exists(),
                    "recommendations_report": RECOMMENDATIONS_JSON_FILE.exists(),
                    "metadata_source": "kinopoisk",
                    "recommendations_enabled": False,
                }).encode()
                content_type = "application/json; charset=utf-8"
            elif path == "/kinopoisk.js":
                raw = ((APP_DIR / 'profiles-client.js').read_bytes() if (APP_DIR / 'profiles-client.js').is_file() else b'') + b'\n' + (APP_DIR / 'client-defaults.js').read_bytes() + b'\n' + PLUGIN_FILE.read_bytes() + b'\n' + (APP_DIR / 'track-memory.js').read_bytes()
                content_type = "application/javascript; charset=utf-8"
            elif path == "/report.json":
                raw = REPORT_JSON_FILE.read_bytes()
                content_type = "application/json; charset=utf-8"
            elif path == "/report.md":
                raw = REPORT_MD_FILE.read_bytes()
                content_type = "text/markdown; charset=utf-8"
            elif path == "/recommendations.json":
                raw = RECOMMENDATIONS_JSON_FILE.read_bytes()
                content_type = "application/json; charset=utf-8"
            elif path == "/recommendations.md":
                raw = RECOMMENDATIONS_MD_FILE.read_bytes()
                content_type = "text/markdown; charset=utf-8"
            elif path == "/airing.json":
                report = json.loads(REPORT_JSON_FILE.read_text(encoding="utf-8"))
                raw = json.dumps({
                    "generated_at": report["generated_at"],
                    "groups": [
                        {"profile_id": item["profile_id"], "title": "Сейчас выходят", "items": item["airing_now"]}
                        for item in report["profiles"]
                    ],
                }, ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif path == "/platforms.json":
                connection = direct_connection()
                try:
                    raw = json.dumps({
                        "generated_at": int(time.time()),
                        "platforms": origin_platform_report(connection),
                    }, ensure_ascii=False).encode("utf-8")
                finally:
                    connection.close()
                content_type = "application/json; charset=utf-8"
            elif path == "/card-ratings.json":
                raw = json.dumps(card_ratings(parse_qs(parsed_url.query), profile_id), ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                raw = DATA_FILE.read_bytes()
                content_type = "application/json; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except FileNotFoundError:
            self.send_error(503, "initial synchronization is not finished")

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    if not PROFILE_ID.isdigit():
        raise SystemExit("Set KINOPOISK_PROFILE_ID to your public numeric profile ID")
    if os.environ.get("SERVE") == "1":
        from home_cache import Cache, start_worker
        HOME_CACHE = Cache(os.environ.get("HOME_CACHE_DB", DATA_FILE.parent / "home-cache.sqlite3"))
        start_worker(HOME_CACHE, PROFILE_ID, LAMPAC_URL, home_personal_data)
        from home_cache import kinopoisk_enabled
        if kinopoisk_enabled():
            snapshot_database("before-candidates")
            threading.Thread(target=refresh_loop, daemon=True).start()
            threading.Thread(target=enrichment_loop, daemon=True).start()
        # homecinema-cloud-worker
        from cloud_disk import manager
        from profiles import ensure
        connection = open_database()
        try:
            ensure(connection, PROFILE_ID, PROFILE_DISPLAY_NAME)
        finally:
            connection.close()
        manager(direct_connection, PROFILE_ID, DATA_FILE.parent / 'cloud')
        ThreadingHTTPServer(("0.0.0.0", 9120), Handler).serve_forever()
    else:
        print(json.dumps(sync(), ensure_ascii=False, indent=2))

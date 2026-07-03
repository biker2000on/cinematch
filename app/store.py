"""SQLite-backed state: metadata cache, Plex item cache, key/value blobs."""
import json
import os
import sqlite3
import threading
import time

from .config import config


class Store:
    def __init__(self, path: str | None = None):
        path = path or os.path.join(config.DATA_DIR, "cinematch.db")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta_cache (
                tmdb_id INTEGER PRIMARY KEY,
                json TEXT,
                fetched_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plex_item_cache (
                rating_key TEXT PRIMARY KEY,
                tmdb_id INTEGER,
                title TEXT,
                user_rating REAL,
                view_count INTEGER,
                fetched_at REAL NOT NULL
            );
            """
        )
        self._db.commit()

    # -- kv ---------------------------------------------------------------
    def get_json(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_json(self, key: str, value) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
            self._db.commit()

    # -- movie metadata cache ----------------------------------------------
    def get_meta(self, tmdb_id: int, max_age_days: float):
        with self._lock:
            row = self._db.execute(
                "SELECT json, fetched_at FROM meta_cache WHERE tmdb_id=?", (tmdb_id,)
            ).fetchone()
        if not row:
            return None
        if time.time() - row[1] > max_age_days * 86400:
            return None
        return json.loads(row[0]) if row[0] is not None else {"__missing__": True}

    def set_meta(self, tmdb_id: int, data) -> None:
        payload = None if data is None else json.dumps(data)
        with self._lock:
            self._db.execute(
                "INSERT INTO meta_cache(tmdb_id,json,fetched_at) VALUES(?,?,?) "
                "ON CONFLICT(tmdb_id) DO UPDATE SET json=excluded.json, fetched_at=excluded.fetched_at",
                (tmdb_id, payload, time.time()),
            )
            self._db.commit()

    # -- plex rating-key resolution cache -----------------------------------
    def get_plex_item(self, rating_key: str):
        with self._lock:
            row = self._db.execute(
                "SELECT tmdb_id, title, user_rating, view_count, fetched_at FROM plex_item_cache WHERE rating_key=?",
                (rating_key,),
            ).fetchone()
        if not row:
            return None
        return {"tmdb_id": row[0], "title": row[1], "user_rating": row[2], "view_count": row[3], "fetched_at": row[4]}

    def set_plex_item(self, rating_key: str, tmdb_id, title, user_rating, view_count) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO plex_item_cache(rating_key,tmdb_id,title,user_rating,view_count,fetched_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(rating_key) DO UPDATE SET tmdb_id=excluded.tmdb_id, "
                "title=excluded.title, user_rating=excluded.user_rating, view_count=excluded.view_count, "
                "fetched_at=excluded.fetched_at",
                (rating_key, tmdb_id, title, user_rating, view_count, time.time()),
            )
            self._db.commit()


store = Store()

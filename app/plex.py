"""Plex watch-history collector.

Walks /status/sessions/history/all (all accounts on the server), keeps movie
entries inside the history window, and resolves each rating key to a TMDB id
via /library/metadata/{key} (cached in SQLite — items get re-resolved weekly
so ratings/view counts stay fresh).
"""
import logging
import time

import httpx

from .config import config
from .store import store

log = logging.getLogger("cinematch.plex")

PAGE_SIZE = 500
ITEM_CACHE_DAYS = 7


async def collect(client: httpx.AsyncClient) -> dict[int, dict]:
    """Return {tmdb_id: {title, last_watched, play_count, user_rating, source}}."""
    if not (config.PLEX_URL and config.PLEX_TOKEN):
        log.info("plex not configured, skipping")
        return {}

    cutoff = time.time() - config.HISTORY_DAYS * 86400
    headers = {"Accept": "application/json", "X-Plex-Token": config.PLEX_TOKEN}

    # 1. page through history, aggregate by ratingKey
    by_key: dict[str, dict] = {}
    start = 0
    while True:
        r = await client.get(
            f"{config.PLEX_URL}/status/sessions/history/all",
            params={
                "sort": "viewedAt:desc",
                "X-Plex-Container-Start": start,
                "X-Plex-Container-Size": PAGE_SIZE,
            },
            headers=headers,
        )
        r.raise_for_status()
        container = r.json().get("MediaContainer", {})
        items = container.get("Metadata", [])
        if not items:
            break
        stop = False
        for it in items:
            viewed_at = it.get("viewedAt", 0)
            if viewed_at < cutoff:
                stop = True
                break
            if it.get("type") != "movie" or not it.get("ratingKey"):
                continue
            k = it["ratingKey"]
            agg = by_key.setdefault(k, {"title": it.get("title"), "last_watched": 0, "plays": 0})
            agg["last_watched"] = max(agg["last_watched"], viewed_at)
            agg["plays"] += 1
        if stop or len(items) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    log.info("plex: %d watched movies in history window", len(by_key))

    # 2. resolve rating keys -> tmdb ids (cache-first)
    out: dict[int, dict] = {}
    for key, agg in by_key.items():
        cached = store.get_plex_item(key)
        if cached and time.time() - cached["fetched_at"] < ITEM_CACHE_DAYS * 86400:
            info = cached
        else:
            info = await _resolve(client, key, headers)
        if not info or not info.get("tmdb_id"):
            continue
        tmdb_id = int(info["tmdb_id"])
        entry = out.setdefault(
            tmdb_id,
            {"title": info.get("title") or agg["title"], "last_watched": 0, "play_count": 0,
             "user_rating": None, "sources": set()},
        )
        entry["last_watched"] = max(entry["last_watched"], agg["last_watched"])
        entry["play_count"] += max(agg["plays"], info.get("view_count") or 0)
        if info.get("user_rating"):
            entry["user_rating"] = info["user_rating"]
        entry["sources"].add("plex")
    return out


async def library_tmdb_ids(client: httpx.AsyncClient) -> set[int]:
    """TMDB ids of every movie in every Plex movie library (watched or not)."""
    if not (config.PLEX_URL and config.PLEX_TOKEN):
        return set()
    headers = {"Accept": "application/json", "X-Plex-Token": config.PLEX_TOKEN}
    r = await client.get(f"{config.PLEX_URL}/library/sections", headers=headers)
    r.raise_for_status()
    sections = [d["key"] for d in r.json()["MediaContainer"].get("Directory", []) if d.get("type") == "movie"]

    ids: set[int] = set()
    for key in sections:
        start = 0
        while True:
            r = await client.get(
                f"{config.PLEX_URL}/library/sections/{key}/all",
                params={
                    "type": 1,
                    "includeGuids": 1,
                    "X-Plex-Container-Start": start,
                    "X-Plex-Container-Size": 1000,
                },
                headers=headers,
            )
            r.raise_for_status()
            container = r.json().get("MediaContainer", {})
            items = container.get("Metadata", [])
            for it in items:
                for g in it.get("Guid", []):
                    gid = g.get("id", "")
                    if gid.startswith("tmdb://"):
                        ids.add(int(gid.removeprefix("tmdb://")))
                        break
            start += len(items)
            if not items or start >= container.get("totalSize", 0):
                break
    log.info("plex: %d movies in library catalog", len(ids))
    return ids


async def _resolve(client: httpx.AsyncClient, rating_key: str, headers: dict) -> dict | None:
    try:
        r = await client.get(f"{config.PLEX_URL}/library/metadata/{rating_key}", headers=headers)
        if r.status_code == 404:
            store.set_plex_item(rating_key, None, None, None, None)
            return None
        r.raise_for_status()
        meta = r.json()["MediaContainer"]["Metadata"][0]
    except Exception as e:  # deleted items, transient errors
        log.warning("plex: failed to resolve ratingKey=%s: %s", rating_key, e)
        return None

    tmdb_id = None
    for g in meta.get("Guid", []):
        gid = g.get("id", "")
        if gid.startswith("tmdb://"):
            tmdb_id = int(gid.removeprefix("tmdb://"))
            break
    info = {
        "tmdb_id": tmdb_id,
        "title": meta.get("title"),
        "user_rating": meta.get("userRating"),
        "view_count": meta.get("viewCount"),
    }
    store.set_plex_item(rating_key, tmdb_id, info["title"], info["user_rating"], info["view_count"])
    return info

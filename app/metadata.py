"""Movie metadata via Radarr's public metadata proxy (api.radarr.video).

Same source Radarr itself uses — TMDB-derived, includes a Recommendations
list per movie, and needs no API key. Responses are cached in SQLite.
"""
import asyncio
import logging

import httpx

from .config import config
from .store import store

log = logging.getLogger("cinematch.metadata")

_sem: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(config.CONCURRENCY)
    return _sem


async def get_movie(client: httpx.AsyncClient, tmdb_id: int) -> dict | None:
    """Fetch (cache-first) metadata for one movie. None if unknown to TMDB."""
    cached = store.get_meta(tmdb_id, config.METADATA_CACHE_DAYS)
    if cached is not None:
        return None if cached.get("__missing__") else cached

    async with _semaphore():
        try:
            r = await client.get(f"{config.METADATA_URL}/movie/{tmdb_id}")
        except httpx.HTTPError as e:
            log.warning("metadata fetch failed for tmdb=%s: %s", tmdb_id, e)
            return None
    if r.status_code == 404:
        store.set_meta(tmdb_id, None)
        return None
    if r.status_code != 200:
        log.warning("metadata fetch tmdb=%s -> HTTP %s", tmdb_id, r.status_code)
        return None
    data = r.json()
    store.set_meta(tmdb_id, data)
    return data


def tmdb_rating(meta: dict) -> tuple[float, int]:
    tm = (meta.get("MovieRatings") or {}).get("Tmdb") or {}
    return float(tm.get("Value") or 0), int(tm.get("Count") or 0)


def poster(meta: dict) -> str | None:
    for img in meta.get("Images") or []:
        if img.get("CoverType") == "Poster":
            return img.get("Url")
    return None

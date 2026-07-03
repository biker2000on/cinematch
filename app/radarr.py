"""Radarr v3 API client (library + import exclusions)."""
import logging

import httpx

from .config import config

log = logging.getLogger("cinematch.radarr")


def _headers() -> dict:
    return {"X-Api-Key": config.RADARR_API_KEY}


async def library_tmdb_ids(client: httpx.AsyncClient) -> set[int]:
    r = await client.get(f"{config.RADARR_URL}/api/v3/movie", headers=_headers())
    r.raise_for_status()
    ids = {m["tmdbId"] for m in r.json() if m.get("tmdbId")}
    log.info("radarr: %d movies in library", len(ids))
    return ids


async def exclusion_tmdb_ids(client: httpx.AsyncClient) -> set[int]:
    r = await client.get(f"{config.RADARR_URL}/api/v3/exclusions", headers=_headers())
    if r.status_code != 200:
        log.warning("radarr exclusions -> HTTP %s (ignoring)", r.status_code)
        return set()
    return {e["tmdbId"] for e in r.json() if e.get("tmdbId")}

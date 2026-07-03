"""Jellyfin watch-history collector.

Aggregates played movies across all Jellyfin users, using each item's TMDB
provider id and per-user playback data (LastPlayedDate, PlayCount, rating).
"""
import logging
import time
from datetime import datetime, timezone

import httpx

from .config import config

log = logging.getLogger("cinematch.jellyfin")


def _parse_date(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        # e.g. 2026-01-12T00:13:35.3075378Z — trim sub-second noise for fromisoformat
        s = s.rstrip("Z")
        if "." in s:
            head, frac = s.split(".", 1)
            s = f"{head}.{frac[:6]}"
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


async def collect(client: httpx.AsyncClient) -> dict[int, dict]:
    """Return {tmdb_id: {title, last_watched, play_count, user_rating, sources}}."""
    if not (config.JELLYFIN_URL and config.JELLYFIN_API_KEY):
        log.info("jellyfin not configured, skipping")
        return {}

    headers = {"X-Emby-Token": config.JELLYFIN_API_KEY}
    r = await client.get(f"{config.JELLYFIN_URL}/Users", headers=headers)
    r.raise_for_status()
    users = r.json()

    cutoff = time.time() - config.HISTORY_DAYS * 86400
    out: dict[int, dict] = {}
    for user in users:
        start = 0
        while True:
            r = await client.get(
                f"{config.JELLYFIN_URL}/Users/{user['Id']}/Items",
                params={
                    "IncludeItemTypes": "Movie",
                    "Filters": "IsPlayed",
                    "Recursive": "true",
                    "Fields": "ProviderIds",
                    "SortBy": "DatePlayed",
                    "SortOrder": "Descending",
                    "StartIndex": start,
                    "Limit": 200,
                },
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("Items", [])
            for it in items:
                tmdb = (it.get("ProviderIds") or {}).get("Tmdb")
                if not tmdb:
                    continue
                ud = it.get("UserData") or {}
                last = _parse_date(ud.get("LastPlayedDate"))
                if last and last < cutoff:
                    continue
                tmdb_id = int(tmdb)
                entry = out.setdefault(
                    tmdb_id,
                    {"title": it.get("Name"), "last_watched": 0, "play_count": 0,
                     "user_rating": None, "sources": set()},
                )
                entry["last_watched"] = max(entry["last_watched"], last)
                entry["play_count"] += ud.get("PlayCount") or 1
                entry["sources"].add("jellyfin")
            start += len(items)
            if start >= data.get("TotalRecordCount", 0) or not items:
                break
    log.info("jellyfin: %d watched movies across %d users", len(out), len(users))
    return out

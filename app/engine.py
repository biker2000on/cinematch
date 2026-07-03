"""Recommendation engine.

Pipeline per run:
  1. Collect watch history from Plex + Jellyfin, merged by TMDB id.
  2. Weight each watched movie into a "seed": recency decay (half-life),
     personal-rating boost, rewatch boost.
  3. For each seed, pull its Recommendations from the metadata proxy; each
     candidate accumulates seed_weight * position_decay.
  4. Build a genre taste profile from the seeds and boost candidates that
     match it.
  5. Drop anything already in Radarr, on Radarr's exclusion list, or already
     watched; enforce quality floors (TMDB rating/votes, year, runtime,
     already released).
  6. Rank, keep the top N, persist with "because you watched" reasons.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from . import jellyfin, metadata, plex, radarr
from .config import config
from .store import store

log = logging.getLogger("cinematch.engine")

_run_lock = asyncio.Lock()


def _seed_weight(entry: dict, now: float) -> float:
    age_days = max(0.0, (now - entry["last_watched"]) / 86400) if entry["last_watched"] else config.HISTORY_DAYS
    recency = 0.5 ** (age_days / config.HALF_LIFE_DAYS)
    rating = entry.get("user_rating")
    quality = 0.25 + (rating / 10) * 1.5 if rating else 1.0  # 10/10 -> 1.75x, 5/10 -> 1.0x, 1/10 -> 0.4x
    plays = min(entry.get("play_count") or 1, 4)
    rewatch = 1 + 0.25 * (plays - 1)
    return recency * quality * rewatch


def _released(meta: dict, now_iso: str) -> bool:
    for field in ("DigitalRelease", "PhysicalRelease", "InCinema", "Premier"):
        d = meta.get(field)
        if d and d <= now_iso:
            return True
    return False


async def run() -> dict:
    """Execute one full refresh. Returns run summary."""
    async with _run_lock:
        return await _run_inner()


async def _run_inner() -> dict:
    started = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=30) as client:
        plex_hist, jf_hist, library, exclusions = await asyncio.gather(
            plex.collect(client),
            jellyfin.collect(client),
            radarr.library_tmdb_ids(client),
            radarr.exclusion_tmdb_ids(client),
        )

        # merge histories by tmdb id
        watched: dict[int, dict] = {}
        for hist in (plex_hist, jf_hist):
            for tmdb_id, e in hist.items():
                cur = watched.get(tmdb_id)
                if cur:
                    cur["last_watched"] = max(cur["last_watched"], e["last_watched"])
                    cur["play_count"] += e["play_count"]
                    cur["user_rating"] = cur["user_rating"] or e["user_rating"]
                    cur["sources"] |= e["sources"]
                else:
                    watched[tmdb_id] = dict(e)

        now = time.time()
        seeds = sorted(
            ({"tmdb_id": k, "weight": _seed_weight(v, now), **v} for k, v in watched.items()),
            key=lambda s: s["weight"],
            reverse=True,
        )[: config.MAX_SEEDS]
        log.info("engine: %d watched movies -> %d seeds", len(watched), len(seeds))

        # fetch seed metadata (for recommendations + genre profile)
        seed_metas = await asyncio.gather(*(metadata.get_movie(client, s["tmdb_id"]) for s in seeds))

        # genre taste profile (weight-normalized)
        genre_profile: dict[str, float] = {}
        for s, meta in zip(seeds, seed_metas):
            if not meta:
                continue
            for g in meta.get("Genres") or []:
                genre_profile[g] = genre_profile.get(g, 0) + s["weight"]
        total_g = sum(genre_profile.values()) or 1.0
        genre_profile = {g: w / total_g for g, w in genre_profile.items()}

        # accumulate candidates
        candidates: dict[int, dict] = {}
        blocked = set(watched) | library | exclusions
        for s, meta in zip(seeds, seed_metas):
            if not meta:
                continue
            for idx, rec in enumerate(meta.get("Recommendations") or []):
                cid = rec.get("TmdbId")
                if not cid or cid in blocked:
                    continue
                c = candidates.setdefault(cid, {"tmdb_id": cid, "score": 0.0, "because": []})
                contribution = s["weight"] / (1 + 0.05 * idx)
                c["score"] += contribution
                c["because"].append((s.get("title") or str(s["tmdb_id"]), contribution))

        log.info("engine: %d raw candidates", len(candidates))

        # enrich top candidates (cap enrichment to keep runs bounded)
        top = sorted(candidates.values(), key=lambda c: c["score"], reverse=True)[: config.MAX_RECOMMENDATIONS * 8]
        metas = await asyncio.gather(*(metadata.get_movie(client, c["tmdb_id"]) for c in top))

    results = []
    excluded_genres = set(config.EXCLUDE_GENRES)
    for c, meta in zip(top, metas):
        if not meta:
            continue
        rating, votes = metadata.tmdb_rating(meta)
        genres = meta.get("Genres") or []
        if rating < config.MIN_TMDB_RATING or votes < config.MIN_TMDB_VOTES:
            continue
        if (meta.get("Year") or 0) < config.MIN_YEAR:
            continue
        if (meta.get("Runtime") or 0) < config.MIN_RUNTIME:
            continue
        if excluded_genres and excluded_genres & {g.lower() for g in genres}:
            continue
        if not _released(meta, now_iso):
            continue
        affinity = sum(genre_profile.get(g, 0.0) for g in genres)
        final = c["score"] * (1 + config.GENRE_BOOST * affinity)
        because = [t for t, _ in sorted(c["because"], key=lambda x: x[1], reverse=True)[:3]]
        results.append({
            "id": c["tmdb_id"],                    # Radarr Custom List reads this field
            "title": meta.get("Title"),
            "year": meta.get("Year"),
            "score": round(final, 3),
            "rating": rating,
            "votes": votes,
            "genres": genres,
            "poster": metadata.poster(meta),
            "overview": (meta.get("Overview") or "")[:400],
            "because": because,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[: config.MAX_RECOMMENDATIONS]

    summary = {
        "started": now_iso,
        "duration_s": round(time.time() - started, 1),
        "watched_total": len(watched),
        "plex_watched": len(plex_hist),
        "jellyfin_watched": len(jf_hist),
        "seeds": len(seeds),
        "library_size": len(library),
        "candidates": len(candidates),
        "recommendations": len(results),
        "genre_profile": dict(sorted(genre_profile.items(), key=lambda x: -x[1])[:8]),
    }
    store.set_json("latest_recommendations", results)
    store.set_json("last_run", summary)
    log.info("engine: run complete in %ss -> %d recommendations", summary["duration_s"], len(results))
    return summary

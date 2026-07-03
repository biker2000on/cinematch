"""Configuration from environment variables."""
import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


class Config:
    # Connections
    PLEX_URL = os.environ.get("PLEX_URL", "").rstrip("/")
    PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "")
    JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "").rstrip("/")
    JELLYFIN_API_KEY = os.environ.get("JELLYFIN_API_KEY", "")
    RADARR_URL = os.environ.get("RADARR_URL", "").rstrip("/")
    RADARR_API_KEY = os.environ.get("RADARR_API_KEY", "")
    METADATA_URL = os.environ.get("METADATA_URL", "https://api.radarr.video/v1").rstrip("/")

    # Engine knobs
    HISTORY_DAYS = _int("HISTORY_DAYS", 730)          # how far back watch history counts
    HALF_LIFE_DAYS = _float("HALF_LIFE_DAYS", 90)     # recency decay half-life for seeds
    MAX_SEEDS = _int("MAX_SEEDS", 150)                # top-N watched movies used as seeds
    MAX_RECOMMENDATIONS = _int("MAX_RECOMMENDATIONS", 30)
    MIN_TMDB_RATING = _float("MIN_TMDB_RATING", 6.3)
    MIN_TMDB_VOTES = _int("MIN_TMDB_VOTES", 300)
    MIN_YEAR = _int("MIN_YEAR", 1970)
    MIN_RUNTIME = _int("MIN_RUNTIME", 60)             # minutes; skips shorts
    GENRE_BOOST = _float("GENRE_BOOST", 0.5)          # strength of taste-profile genre boost
    EXCLUDE_GENRES = [g.strip().lower() for g in os.environ.get("EXCLUDE_GENRES", "").split(",") if g.strip()]

    # Operation
    REFRESH_HOURS = _float("REFRESH_HOURS", 12)
    METADATA_CACHE_DAYS = _float("METADATA_CACHE_DAYS", 7)
    PORT = _int("PORT", 8585)
    DATA_DIR = os.environ.get("DATA_DIR", "/data")
    CONCURRENCY = _int("CONCURRENCY", 8)


config = Config()

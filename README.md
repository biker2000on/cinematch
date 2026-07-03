# cinematch

Netflix-style movie recommendations for Radarr, driven by your actual Plex and
Jellyfin watch history.

## How it works

1. Pulls watch history from **Plex** (all accounts) and **Jellyfin** (all users),
   merged by TMDB id.
2. Turns each watched movie into a weighted **seed**: recent watches count more
   (90-day half-life), your star ratings boost/penalize, rewatches boost.
3. Pulls per-movie recommendations from Radarr's own metadata proxy
   (`api.radarr.video`, TMDB-derived, no API key needed) and aggregates scores
   across all seeds, plus a genre taste-profile boost.
4. Filters out: everything already in Radarr, Radarr's import exclusions,
   everything you've watched, everything already in your Plex/Jellyfin library
   catalogs (even unwatched), and low-rated / low-vote / unreleased / too-short
   movies.
5. Serves the top picks (default 30) at `GET /api/list` in the exact format
   Radarr's **Custom Lists** import list consumes: `[{"id": <tmdbId>}, ...]`.

Radarr polls the list on its normal import-list schedule, auto-adds the movies,
and (with *Search on Add*) starts downloading them. As movies land in Radarr or
get watched, they drop off the list and new ones surface — a rolling
"recommended for you" queue.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `/` | Dashboard: posters, scores, "because you watched" reasons |
| `/api/list` | Radarr Custom List JSON |
| `/api/recommendations` | Full recommendation details + last-run stats |
| `POST /api/refresh` | Force a refresh now |
| `/api/status`, `/healthz` | Monitoring |

## Configuration (env)

Required: `PLEX_URL`, `PLEX_TOKEN`, `JELLYFIN_URL`, `JELLYFIN_API_KEY`,
`RADARR_URL`, `RADARR_API_KEY`.

Tuning (defaults): `HISTORY_DAYS` (730), `HALF_LIFE_DAYS` (90), `MAX_SEEDS`
(150), `MAX_RECOMMENDATIONS` (30), `MIN_TMDB_RATING` (6.3), `MIN_TMDB_VOTES`
(300), `MIN_YEAR` (1970), `MIN_RUNTIME` (60), `GENRE_BOOST` (0.5),
`EXCLUDE_GENRES` (csv, empty), `REFRESH_HOURS` (12).

## Image

Published to `ghcr.io/biker2000on/cinematch:latest` by GitHub Actions on every
push to `main`. For local dev builds: `docker build -t cinematch:dev .`

## Radarr side

Settings → Lists → add **Custom Lists** with URL `http://cinematch:8585/api/list`,
Enable Automatic Add + Search on Add, pick quality profile / root folder /
minimum availability = Released.

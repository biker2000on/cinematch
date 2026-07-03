"""FastAPI app: Radarr-compatible list endpoint, dashboard, refresh loop."""
import asyncio
import contextlib
import html
import logging
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import engine
from .config import config
from .store import store

log = logging.getLogger("cinematch.web")

_refresh_task: asyncio.Task | None = None


async def _refresh_loop() -> None:
    while True:
        last = store.get_json("last_run")
        stale = True
        if last:
            try:
                from datetime import datetime
                started = datetime.fromisoformat(last["started"]).timestamp()
                stale = time.time() - started > config.REFRESH_HOURS * 3600
            except (KeyError, ValueError):
                stale = True
        if stale:
            try:
                await engine.run()
            except Exception:
                log.exception("scheduled refresh failed")
        await asyncio.sleep(600)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    global _refresh_task
    _refresh_task = asyncio.create_task(_refresh_loop())
    yield
    _refresh_task.cancel()


app = FastAPI(title="cinematch", lifespan=_lifespan)


FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<text y='.9em' font-size='90'>\U0001f3ac</text></svg>"
)


@app.get("/favicon.svg", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=FAVICON_SVG, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/list")
async def radarr_list():
    """Radarr 'Custom Lists' endpoint — array of objects with tmdb `id`."""
    recs = store.get_json("latest_recommendations", [])
    return JSONResponse([{"id": r["id"], "title": r["title"]} for r in recs])


@app.get("/api/recommendations")
async def recommendations():
    return {"last_run": store.get_json("last_run"), "recommendations": store.get_json("latest_recommendations", [])}


@app.post("/api/refresh")
async def refresh():
    summary = await engine.run()
    return summary


@app.get("/api/status")
async def status():
    return {"last_run": store.get_json("last_run")}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    recs = store.get_json("latest_recommendations", [])
    run = store.get_json("last_run") or {}
    cards = []
    for r in recs:
        because = ", ".join(html.escape(b) for b in r.get("because", []))
        poster = html.escape(r.get("poster") or "")
        img = f'<img src="{poster}" loading="lazy" alt="">' if poster else '<div class="noposter"></div>'
        cards.append(f"""
        <div class="card">
          {img}
          <div class="body">
            <div class="title">{html.escape(str(r.get('title')))} <span class="year">({r.get('year')})</span></div>
            <div class="meta">&#9733; {r.get('rating')} &middot; {html.escape(', '.join(r.get('genres', [])[:3]))}</div>
            <div class="because">Because you watched: {because}</div>
          </div>
        </div>""")
    profile = " &middot; ".join(f"{html.escape(g)} {round(w * 100)}%" for g, w in (run.get("genre_profile") or {}).items())
    body = f"""<!doctype html><html><head><meta charset="utf-8"><title>cinematch</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <style>
      body {{ font-family: system-ui, sans-serif; background:#111; color:#eee; margin:0; padding:2rem; }}
      h1 {{ margin:0 0 .25rem; }} .sub {{ color:#999; margin-bottom:1.5rem; }}
      .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:1rem; }}
      .card {{ display:flex; background:#1c1c1e; border-radius:10px; overflow:hidden; }}
      .card img, .noposter {{ width:92px; min-width:92px; object-fit:cover; background:#333; }}
      .body {{ padding:.7rem .9rem; }} .title {{ font-weight:600; }} .year {{ color:#999; font-weight:400; }}
      .meta {{ color:#bbb; font-size:.85rem; margin:.25rem 0; }}
      .because {{ color:#8ab4f8; font-size:.8rem; }}
      button {{ background:#2563eb; color:#fff; border:0; border-radius:6px; padding:.5rem 1rem; cursor:pointer; }}
    </style></head><body>
    <h1>cinematch</h1>
    <div class="sub">
      {len(recs)} recommendations &middot; last run {html.escape(str(run.get('started', 'never')))}
      ({run.get('watched_total', 0)} watched movies: {run.get('plex_watched', 0)} plex / {run.get('jellyfin_watched', 0)} jellyfin
      &middot; {run.get('seeds', 0)} seeds &middot; {run.get('candidates', 0)} candidates)<br>
      taste profile: {profile or 'n/a'}<br><br>
      <button onclick="fetch('/api/refresh',{{method:'POST'}}).then(()=>location.reload())">Refresh now</button>
    </div>
    <div class="grid">{''.join(cards)}</div>
    </body></html>"""
    return HTMLResponse(body)

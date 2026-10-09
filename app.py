"""FSAC Local Wrapper — FastAPI app.

Channels the live FSAC backend (WS.php on fsac.univh2c.ma) into clean JSON
endpoints and serves a modern localhost UI.

Run:  uvicorn app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup

from config import CACHE_TTL, ENABLE_PROXY, FSAC_ORIGIN, PROXY_ALLOWED_HOSTS
from fsac.client import close_client, get_client, init_client, loads_deep
from fsac.models import (
    Article,
    FeedResponse,
    HealthResponse,
    NavLink,
    NavResponse,
    Stat,
    StatsResponse,
)
from fsac.normalize import (
    KIND_LABELS,
    clean_text,
    normalize_article,
    normalize_list,
    normalize_recrut_list,
)
from fsac.pages import PAGE_SLUGS, normalize_page, summarize_page

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cached_flag(cached: bool) -> dict:
    return {"cached": cached, "fetched_at": now_iso()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_client()
    yield
    await close_client()


app = FastAPI(
    title="FSAC Local Wrapper",
    description="Modern localhost wrapper around the FSAC website (fsac.ac.ma / fsac.univh2c.ma).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store_api(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------
@app.get("/api/health", response_model=HealthResponse)
async def api_health():
    client = get_client()
    return HealthResponse(
        status="ok",
        origin=FSAC_ORIGIN,
        cache_ttl=CACHE_TTL,
        cache_entries=client.cache_size(),
        server_time=now_iso(),
    )


# ---------------------------------------------------------------------------
# unified feed
# ---------------------------------------------------------------------------
async def build_feed(force: bool) -> tuple[list[dict], dict]:
    """Merge action=all groups + paged lists into one deduped feed."""
    client = get_client()

    results = await asyncio.gather(
        client.all_groups(force=force),
        client.articles(force=force),
        client.recrutements(force=force),
        return_exceptions=True,
    )
    groups, articles, recruts = results
    if isinstance(groups, Exception) and isinstance(articles, Exception):
        raise HTTPException(status_code=502, detail=f"FSAC unreachable: {groups}")

    items: list[dict] = []
    if isinstance(groups, dict):
        items += normalize_list(groups.get("annonces") or [], "annonce")
        items += normalize_list(groups.get("events") or [], "event")
        items += normalize_list(groups.get("actus") or [], "actu")
        items += normalize_list(groups.get("recruts") or [], "recrut")
    if not isinstance(articles, Exception):
        items += normalize_list(articles, "annonce")
    if not isinstance(recruts, Exception):
        items += normalize_recrut_list(recruts)

    # dedupe by id+kind, merge (later sources only fill missing)
    merged: dict[tuple[str, str], dict] = {}
    for it in items:
        key = (it["kind"], it["id"])
        if key not in merged:
            merged[key] = it
        else:
            cur = merged[key]
            if not cur.get("excerpt") and it.get("excerpt"):
                cur["excerpt"] = it["excerpt"]
            if not cur.get("image") and it.get("image"):
                cur["image"] = it["image"]
            if not cur.get("date") and it.get("date"):
                cur["date"] = it["date"]
                cur["date_display"] = it.get("date_display")

    deduped = list(merged.values())
    deduped.sort(key=lambda x: x["date"] or "", reverse=True)

    counts: dict[str, int] = {"total": len(deduped)}
    for it in deduped:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    for kind, label in KIND_LABELS.items():
        counts.setdefault(kind, 0)

    return deduped, counts


@app.get("/api/feed", response_model=FeedResponse)
async def api_feed(force: bool = Query(False, description="Bypass cache")):
    items, counts = await build_feed(force)
    return FeedResponse(
        items=items,
        fetched_at=now_iso(),
        cached=not force,
        counts=counts,
    )


# ---------------------------------------------------------------------------
# article detail
# ---------------------------------------------------------------------------
@app.get("/api/article/{kind}/{item_id}", response_model=Article)
async def api_article(kind: str, item_id: str, force: bool = Query(False)):
    if kind not in KIND_LABELS:
        raise HTTPException(status_code=404, detail=f"Unknown kind '{kind}'")
    client = get_client()
    try:
        if kind == "recrut":
            raw = await client.recrut_detail(item_id, force=force)
        else:
            raw = await client.article_detail(item_id, force=force)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"{kind} {item_id} not found")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FSAC unreachable: {exc}")

    try:
        data = normalize_article(raw, fallback_kind=kind)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"{kind} {item_id} not found")
    return Article(**data)


# ---------------------------------------------------------------------------
# home stats ("La FSAC en chiffres") from static homepage HTML
# ---------------------------------------------------------------------------
@app.get("/api/stats", response_model=StatsResponse)
async def api_stats(force: bool = Query(False)):
    client = get_client()
    try:
        html = await client.homepage_html(force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FSAC homepage unreachable: {exc}")

    soup = BeautifulSoup(html, "lxml")
    section = soup.find(id="chiffres")
    stats: list[Stat] = []
    if section:
        for art in section.find_all("article"):
            num = art.find("span")
            if not num:
                continue
            value = clean_text(num.get_text())
            label = clean_text(art.get_text(" ").replace(num.get_text(), ""))
            digits = value.replace("\u202f", "").replace(" ", "")
            if not digits.isdigit() or not label:
                continue
            stats.append(Stat(value=int(digits), label=label))
    if not stats:
        raise HTTPException(status_code=404, detail="Stats section not found on FSAC homepage")
    return StatsResponse(stats=stats, cached=not force, source=FSAC_ORIGIN + "/front/")


# ---------------------------------------------------------------------------
# navigation (menu from global.json)
# ---------------------------------------------------------------------------
@app.get("/api/nav", response_model=NavResponse)
async def api_nav(force: bool = Query(False)):
    client = get_client()
    try:
        data = await client.global_config(force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"global.json unreachable: {exc}")
    links: list[NavLink] = []
    for entry in data.get("menu") or []:
        if not isinstance(entry, dict):
            continue
        title = clean_text(BeautifulSoup(str(entry.get("title") or ""), "lxml").get_text())
        url = str(entry.get("url") or "").strip()
        if not title or not url or url.startswith("javascript"):
            continue
        links.append(NavLink(title=title, url=url, extern=bool(entry.get("extern"))))
    return NavResponse(links=links, cached=not force)


# ---------------------------------------------------------------------------
# static content pages (présentation, formations, …)
# ---------------------------------------------------------------------------
@app.get("/api/pages")
async def api_pages_list(force: bool = Query(False)):
    client = get_client()
    pages = []
    errors = []
    for slug, label in PAGE_SLUGS.items():
        try:
            raw = await client.page_json(slug, force=force)
            page = normalize_page(raw, slug)
            pages.append(summarize_page(page))
        except Exception as exc:  # keep partial results if one page fails
            errors.append({"slug": slug, "error": str(exc)})
    if not pages and errors:
        raise HTTPException(status_code=502, detail=f"All pages failed: {errors}")
    return {"pages": pages, "errors": errors, "cached": not force}


@app.get("/api/pages/{slug}")
async def api_page(slug: str, force: bool = Query(False)):
    if slug not in PAGE_SLUGS:
        raise HTTPException(status_code=404, detail=f"Unknown page '{slug}'")
    client = get_client()
    try:
        raw = await client.page_json(slug, force=force)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Page upstream failed: {exc}")
    return normalize_page(raw, slug)


# ---------------------------------------------------------------------------
# media proxy (images / attachments) — allowlisted to FSAC hosts only
# ---------------------------------------------------------------------------
@app.get("/api/proxy")
async def api_proxy(url: str = Query(..., description="Absolute FSAC media URL")):
    if not ENABLE_PROXY:
        raise HTTPException(status_code=403, detail="Proxy disabled")
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) URLs")
    if (parsed.netloc or "").lower() not in PROXY_ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail="Host not allowed")

    client = get_client()
    try:
        r = await client.get_bytes(url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream fetch failed: {exc}")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail="Upstream error")

    media_type = r.headers.get("content-type", "application/octet-stream")
    headers = {"X-Upstream-Status": str(r.status_code)}
    etag = r.headers.get("etag") or r.headers.get("last-modified")
    if etag:
        headers["ETag"] = etag
    return Response(content=r.content, media_type=media_type, headers=headers)


# ---------------------------------------------------------------------------
# cache control
# ---------------------------------------------------------------------------
@app.get("/api/cache/clear")
async def api_cache_clear():
    client = get_client()
    n = client.clear_cache()
    return {"cleared": n, "at": now_iso()}


# ---------------------------------------------------------------------------
# static UI
# ---------------------------------------------------------------------------
@app.get("/api/meta")
async def api_meta():
    return {
        "app": "FSAC Local Wrapper",
        "origin": FSAC_ORIGIN,
        "cache_ttl": CACHE_TTL,
        "proxy": ENABLE_PROXY,
        "time": now_iso(),
    }


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", response_class=Response)
async def favicon():
    return Response(status_code=204)

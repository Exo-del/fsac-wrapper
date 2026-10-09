"""Async HTTP client for FSAC's WS.php backend with a small TTL cache.

- Single-flight per cache key: concurrent requests coalesce into one upstream call.
- `force=True` bypasses the cache (real-time refresh).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

import httpx

from config import (
    CACHE_TTL,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RECRUT_SIZE,
    FSAC_GLOBAL_JSON,
    FSAC_HOME,
    FSAC_ORIGIN,
    FSAC_WS,
    HOME_CACHE_TTL,
    REQUEST_TIMEOUT,
    USER_AGENT,
)


def loads_deep(value: Any, depth: int = 3) -> Any:
    """WS.php double-encodes JSON sometimes: unwrap strings repeatedly."""
    while isinstance(value, str) and depth > 0:
        text = value.strip()
        if not text or text[0] not in "[{":
            break
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            break
        depth -= 1
    return value


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[tuple[Any, bool]]:
        hit = self._data.get(key)
        if not hit:
            return None
        expires, value = hit
        if time.monotonic() > expires:
            self._data.pop(key, None)
            return None
        return value, True

    def set(self, key: str, value: Any, ttl: float) -> None:
        self._data[key] = (time.monotonic() + ttl, value)

    def clear(self) -> int:
        n = len(self._data)
        self._data.clear()
        return n

    def __len__(self) -> int:
        return len(self._data)


class FSACClient:
    def __init__(self) -> None:
        self.cache = TTLCache()
        self._http: Optional[httpx.AsyncClient] = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._inflight: dict[str, asyncio.Future] = {}

    # -- lifecycle ---------------------------------------------------------
    def _ensure_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
                },
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()

    # -- cache helpers -----------------------------------------------------
    def cache_size(self) -> int:
        return len(self.cache)

    def clear_cache(self) -> int:
        return self.cache.clear()

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    # -- core fetch --------------------------------------------------------
    async def _cached(self, key: str, ttl: float, force: bool, producer):
        if not force:
            hit = self.cache.get(key)
            if hit is not None:
                return hit[0], True

        async with self._lock(key):
            if not force:
                hit = self.cache.get(key)
                if hit is not None:
                    return hit[0], True
            value = await producer()
            self.cache.set(key, value, ttl)
            return value, False

    async def get_json(self, url: str, params: dict | None = None, *,
                       force: bool = False, ttl: float = CACHE_TTL) -> Any:
        key = "J:" + url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))

        async def produce() -> Any:
            http = self._ensure_http()
            r = await http.get(url, params=params)
            r.raise_for_status()
            try:
                data = r.json()
            except (json.JSONDecodeError, ValueError):
                data = r.text
            return loads_deep(data)

        value, _cached = await self._cached(key, ttl, force, produce)
        return value

    async def get_text(self, url: str, *, force: bool = False,
                       ttl: float = CACHE_TTL) -> str:
        key = "T:" + url

        async def produce() -> str:
            http = self._ensure_http()
            r = await http.get(url)
            r.raise_for_status()
            return r.text

        value, _cached = await self._cached(key, ttl, force, produce)
        return value

    async def get_bytes(self, url: str) -> httpx.Response:
        http = self._ensure_http()
        return await http.get(url)

    # -- FSAC domain endpoints --------------------------------------------
    async def ws(self, action: str, params: dict | None = None, *,
                 force: bool = False, ttl: float = CACHE_TTL) -> Any:
        q = {"action": action}
        if params:
            q.update(params)
        return await self.get_json(FSAC_WS, q, force=force, ttl=ttl)

    async def all_groups(self, *, force: bool = False) -> dict:
        """action=all -> {annonces, events, actus, recruts} (each a list)."""
        raw = await self.ws("all", force=force, ttl=CACHE_TTL)
        if not isinstance(raw, dict):
            raise ValueError("Unexpected WS response for action=all")
        return {k: loads_deep(v) or [] for k, v in raw.items()}

    async def articles(self, nb: int = DEFAULT_PAGE_SIZE, frm: int = 0, *,
                       force: bool = False) -> list:
        data = await self.ws("annonce", {"nb": nb, "from": frm}, force=force)
        data = loads_deep(data)
        return data if isinstance(data, list) else []

    async def recrutements(self, nb: int = DEFAULT_RECRUT_SIZE, frm: int = 0, *,
                           force: bool = False) -> list:
        data = await self.ws("recrut", {"nb": nb, "from": frm}, force=force)
        data = loads_deep(data)
        return data if isinstance(data, list) else []

    async def article_detail(self, article_id: str | int, *, force: bool = False) -> Any:
        """Fetch one article. WS only exposes `annonce`/`actu`/`recrut` for
        single-id lookups; `annonce&id=` serves every TYPE (AN/EV/AC)."""
        detail = await self.ws("annonce", {"id": article_id}, force=force)
        detail = loads_deep(detail)
        if isinstance(detail, list):
            detail = detail[0] if detail else None
        if isinstance(detail, dict) and detail.get("ID"):
            return detail
        detail = await self.ws("actu", {"id": article_id}, force=force)
        detail = loads_deep(detail)
        if isinstance(detail, list):
            detail = detail[0] if detail else None
        if isinstance(detail, dict) and detail.get("ID"):
            return detail
        raise LookupError(f"Article {article_id} not found")

    async def recrut_detail(self, recrut_id: str | int, *, force: bool = False) -> Any:
        detail = await self.ws("recrut", {"id": recrut_id}, force=force)
        detail = loads_deep(detail)
        if isinstance(detail, list):
            detail = detail[0] if detail else None
        if isinstance(detail, dict) and detail.get("ID"):
            return detail
        raise LookupError(f"Recrutement {recrut_id} not found")

    async def global_config(self, *, force: bool = False) -> dict:
        data = await self.get_json(FSAC_GLOBAL_JSON, force=force, ttl=HOME_CACHE_TTL)
        data = loads_deep(data)
        if not isinstance(data, dict):
            raise ValueError("Unexpected global.json payload")
        if isinstance(data.get("menu"), str):
            data["menu"] = loads_deep(data["menu"]) or []
        return data

    async def homepage_html(self, *, force: bool = False) -> str:
        return await self.get_text(FSAC_HOME, force=force, ttl=HOME_CACHE_TTL)

    async def page_json(self, slug: str, *, force: bool = False) -> Any:
        """Fetch /Docs/static_pages/{slug}.json with encoding fallback."""
        url = f"{FSAC_ORIGIN}/Docs/static_pages/{slug}.json"
        key = "P:" + slug

        async def produce() -> Any:
            from .pages import decode_page_json

            http = self._ensure_http()
            r = await http.get(url)
            r.raise_for_status()
            return decode_page_json(r.content)

        value, _cached = await self._cached(key, HOME_CACHE_TTL, force, produce)
        return value


# -- module-level singleton -------------------------------------------------
_client: Optional[FSACClient] = None


def init_client() -> FSACClient:
    global _client
    if _client is None:
        _client = FSACClient()
    return _client


def get_client() -> FSACClient:
    if _client is None:
        return init_client()
    return _client


async def close_client() -> None:
    if _client is not None:
        await _client.aclose()

"""Smoke tests for the FSAC wrapper API (requires network + server running).

Run:  pytest tests/ -v          (server must be up on :8000)
      python tests/test_smoke.py  (same, without pytest)
"""

import os
import sys

import httpx

BASE = os.getenv("WRAPPER_URL", "http://127.0.0.1:8000")


def _get(path, **kw):
    with httpx.Client(timeout=60) as c:
        r = c.get(BASE + path, **kw)
        r.raise_for_status()
        return r.json()


def test_health():
    d = _get("/api/health")
    assert d["status"] == "ok"
    assert d["origin"].startswith("http")


def test_feed_shape():
    d = _get("/api/feed")
    items = d["items"]
    assert len(items) > 0, "feed must not be empty"
    assert d["counts"]["total"] == len(items)
    kinds = {i["kind"] for i in items}
    assert kinds <= {"annonce", "event", "actu", "recrut"}
    for it in items:
        assert it["id"] and it["title"]
        assert it["original_url"].startswith("http")
    # newest first
    dates = [i["date"] or "" for i in items]
    assert dates == sorted(dates, reverse=True)


def test_article_detail():
    d = _get("/api/feed")
    first = next(i for i in d["items"] if i["kind"] == "annonce")
    a = _get(f"/api/article/annonce/{first['id']}")
    assert a["id"] == first["id"]
    assert "<script" not in a["html"].lower()
    for att in a["attachments"]:
        assert att["url"].startswith("http")
    # duplicated leading title must be stripped
    from bs4 import BeautifulSoup

    h = BeautifulSoup(a["html"], "lxml")
    first_h = h.find(["h1", "h2"])
    if first_h:
        assert first_h.get_text(strip=True).lower() != a["title"].strip().lower()


def test_stats():
    d = _get("/api/stats")
    assert len(d["stats"]) >= 5
    assert all(s["value"] > 0 and s["label"] for s in d["stats"])


def test_nav():
    d = _get("/api/nav")
    assert len(d["links"]) >= 3


def test_cache_roundtrip():
    _get("/api/feed")
    with httpx.Client(timeout=30) as c:
        h = c.get(BASE + "/api/health").json()
        assert h["cache_entries"] >= 1
    c = httpx.Client(timeout=30)
    d = c.get(BASE + "/api/cache/clear").json()
    assert d["cleared"] >= 0


def test_proxy_rejects_foreign_host():
    with httpx.Client(timeout=15, follow_redirects=False) as c:
        r = c.get(BASE + "/api/proxy", params={"url": "https://example.com/x.png"})
        assert r.status_code == 403


def test_pages_index():
    d = _get("/api/pages")
    slugs = {p["slug"] for p in d["pages"]}
    assert {"presentation", "departements", "formations", "recherche", "espace_etu"} <= slugs
    for p in d["pages"]:
        assert p["title"] and p["parts"]
        assert all(part.get("key") and part.get("title") for part in p["parts"])


def test_pages_detail():
    d = _get("/api/pages/presentation")
    assert d["slug"] == "presentation"
    assert d["title"]
    assert len(d["parts"]) >= 4
    joined = ""
    for part in d["parts"]:
        html = part.get("html", "")
        assert "<script" not in html.lower()
        joined += html
    assert "/api/proxy?url=" in joined  # local images routed through proxy


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)

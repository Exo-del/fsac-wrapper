# FSAC Wrapper

A modern **localhost wrapper** around the old website of the
*Faculté des Sciences Aïn Chock* (fsac.ac.ma) — real-time data, clean JSON API,
static faculty content, and a light **academic UI** (unofficial proof of
concept, clearly marked as such in the footer).

The official site still works, but it's dated and awkward to browse. This
project reads the **same live backend** the site itself uses
(`WS.php` on `fsac.univh2c.ma`) and re-serves it as:

- a **FastAPI JSON API** (cached, sanitized, normalized)
- a **vanilla HTML/CSS/JS UI** served on `http://127.0.0.1:8000`

```
┌─────────────┐   WS.php?action=…    ┌──────────────────┐   /api/*    ┌──────────────┐
│ fsac.ac.ma  │ ◄──────────────────  │  FSAC Wrapper    │ ◄─────────  │  Browser UI  │
│ (upstream)  │   global.json, HTML  │  (FastAPI, 60s   │   JSON      │  (localhost) │
└─────────────┘                      │   TTL cache)     │             └──────────────┘
                                     └──────────────────┘
```

## Features

- **Academic theme** — light paper palette, serif headings (Source Serif 4),
  institutional blue taken from the real FSAC logo (served locally), sticky
  masthead/nav, prominent PoC disclaimer in the footer
- **Static content pages** — Présentation, Départements, Formations, Recherche,
  Espace étudiant, served from the official `static_pages/*.json` with
  sanitized HTML, section sub-nav, and locally rewritten images
- **Live feed** — annonces, événements, actualités, recrutements, merged,
  deduplicated and sorted newest-first (40+ items with full text excerpts)
- **Article reader drawer** — server-side sanitized HTML, attachments with
  typed icons, prev/next navigation (feed order), deep links (`#annonce/1270`)
- **Media proxy** — images & PDFs stream through `/api/proxy` (host-allowlisted),
  so nothing breaks on hotlink rules
- **Real-time-ish** — 60 s TTL cache, `?force=true` bypass, **Live mode**
  auto-refresh every 60 s, "Nouveau" badges for unseen items
- **FSAC en chiffres** — animated counters parsed from the real homepage
- **Search** — instant, token-based client-side filtering (`/` shortcut)
- **Hash router** — `#/`, `#/actualites`, `#/page/{slug}`, `#annonce/{id}`
- **Polite by design** — identified User-Agent, single-flight cache locks,
  short TTL, no writes upstream, read-only endpoints

## Quick start

```bash
cd fsac-wrapper
./run.sh
# → http://127.0.0.1:8000
```

Or manually:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python runner.py        # or: .venv/bin/uvicorn app:app --port 8000
```

## API

| Endpoint                      | Description                                    |
| ----------------------------- | ---------------------------------------------- |
| `GET /api/feed?force=`        | Unified feed (kind, title, date, excerpt, …)   |
| `GET /api/article/{kind}/{id}`| Full article: sanitized HTML + attachments     |
| `GET /api/stats`              | "La FSAC en chiffres" (parsed from homepage)   |
| `GET /api/pages`              | Index of static pages (slugs, titles, sections)|
| `GET /api/pages/{slug}`       | Full page: sanitized section HTML              |
| `GET /api/nav`                | Official site menu (global.json)               |
| `GET /api/proxy?url=`         | Allowlisted media proxy (FSAC hosts only)      |
| `GET /api/health`             | Status, cache size, origin                     |
| `GET /api/cache/clear`        | Drop the in-memory TTL cache                   |

`kind` ∈ `annonce | event | actu | recrut` (cross-kind lookups resolve
automatically via the upstream `TYPE` field).

## Configuration

Copy `.env.example` to `.env`:

| Var              | Default                    | Meaning                       |
| ---------------- | -------------------------- | ----------------------------- |
| `FSAC_ORIGIN`    | `https://fsac.univh2c.ma`  | Upstream origin               |
| `CACHE_TTL`      | `60`                       | Feed/API cache (seconds)      |
| `HOME_CACHE_TTL` | `600`                      | Homepage/global.json cache    |
| `REQUEST_TIMEOUT`| `12`                       | Upstream timeout (seconds)    |
| `ENABLE_PROXY`   | `true`                     | Media proxy on/off            |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python runner.py &          # server must be running
.venv/bin/pytest tests/ -v
```

## Project layout

```
fsac-wrapper/
├── app.py               # FastAPI routes (feed, article, stats, pages, nav, proxy)
├── config.py            # env-driven configuration
├── runner.py            # launcher (python runner.py)
├── run.sh               # one-shot setup + start
├── fsac/
│   ├── client.py        # async HTTP client + TTL cache + single-flight locks
│   ├── normalize.py     # sanitizer, normalizers, URL rewriting
│   ├── pages.py         # static-page normalization (static_pages/*.json)
│   └── models.py        # pydantic response models
├── static/
│   ├── index.html       # UI shell (masthead, nav, views, drawer, footer)
│   ├── css/styles.css   # light academic theme (paper/serif/blue)
│   ├── js/app.js        # hash router, feed, live mode, search, drawer
│   └── img/             # real FSAC logo
└── tests/test_smoke.py  # end-to-end API smoke tests
```

## Notes

- **Read-only & unofficial.** No authentication, no writes, no scraping of
  personal data. Be polite: keep the cache enabled, don't hammer upstream.
- The upstream site's real home is `https://fsac.univh2c.ma/front/`
  (`www.fsac.ac.ma` just 302s there); the wrapper talks to that origin.
- If FSAC changes its backend, the only files you'd touch are
  `fsac/client.py` (endpoints) and `fsac/normalize.py` (field mapping).

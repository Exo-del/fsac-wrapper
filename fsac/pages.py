"""Static content pages (Présentation, Départements, Formations, …).

FSAC serves these as JSON at /Docs/static_pages/{slug}.json with the shape:
    {"title": str, "parts": [{"key": str, "title"?: str, "html": str}]}
"""

from __future__ import annotations

import json
from typing import Any

from .normalize import clean_text, sanitize_html

PAGE_SLUGS: dict[str, str] = {
    "presentation": "Présentation",
    "departements": "Départements",
    "formations": "Formations",
    "recherche": "Recherche",
    "espace_etu": "Espace étudiant",
}


def decode_page_json(raw: bytes | str) -> dict:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("page payload is not an object")
    return data


def normalize_page(data: dict, slug: str) -> dict:
    title = clean_text(data.get("title")) or PAGE_SLUGS.get(slug, slug.title())
    parts_out: list[dict] = []
    for part in data.get("parts") or []:
        if not isinstance(part, dict):
            continue
        key = clean_text(part.get("key"))
        html = part.get("html") or ""
        if not key and not html.strip():
            continue
        sub = clean_text(part.get("title")) or key
        parts_out.append({
            "key": key or sub,
            "title": sub,
            "html": sanitize_html(html),
        })
    return {"slug": slug, "title": title, "parts": parts_out}


def summarize_page(page: dict) -> dict:
    return {
        "slug": page["slug"],
        "title": page["title"],
        "parts": [{"key": p["key"], "title": p["title"]} for p in page["parts"]],
    }

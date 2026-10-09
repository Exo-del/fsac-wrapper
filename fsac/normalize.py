"""Normalization + HTML sanitization for FSAC payloads.

FSAC returns article HTML from a TinyMCE-ish editor: inline styles, relative
attachment paths, occasional junk. We sanitize to a safe allowlist, rewrite
every media/attachment URL to go through our local proxy, and shape items into
a uniform feed model.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime
from typing import Any, Iterable, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup, NavigableString, Tag

from config import FSAC_FRONT, FSAC_ORIGIN

# ---------------------------------------------------------------------------
# kinds
# ---------------------------------------------------------------------------
TYPE_TO_KIND = {"AN": "annonce", "EV": "event", "AC": "actu", "RH": "recrut"}
KIND_TO_PAGE = {
    "annonce": "annonce.html",
    "event": "event.html",
    "actu": "actu.html",
    "recrut": "recrut.html",
}
KIND_LABELS = {
    "annonce": "Annonce",
    "event": "Événement",
    "actu": "Actualité",
    "recrut": "Recrutement",
}

_ALLOWED_TAGS = {
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "b", "em", "i", "u", "s", "mark", "small", "sub", "sup",
    "ul", "ol", "li", "dl", "dt", "dd",
    "a", "img", "blockquote", "code", "pre",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    "span", "div", "figure", "figcaption",
    "u", "abbr", "cite", "q",
}
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "ol": {"start"},
    "span": set(),  # allowed but attributes stripped (styles removed)
}
_SAFE_URL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "#", "/")

_WS_PAT = re.compile(r"\s+")


def _resolve_fsac_url(href: str, base: str = "front") -> str:
    """Resolve FSAC-relative URLs to absolute origin URLs.

    Handles: ../Docs/..., Docs/..., /Docs/..., /front/images/...,
    images/..., and bare front-office files (tabs.html, contact.html, ...).
    """
    if not href:
        return href
    if href.startswith(("http://", "https://", "mailto:", "tel:", "#", "data:")):
        return href
    if href.startswith("../"):
        return FSAC_ORIGIN + "/" + href.lstrip("./")
    if href.startswith("/Docs/") or href.startswith("Docs/"):
        return FSAC_ORIGIN + "/" + href.lstrip("/")
    if href.startswith("/front/"):
        return FSAC_ORIGIN + href
    if href.startswith("images/") or href.startswith("css/") or href.startswith("js/"):
        return f"{FSAC_FRONT}{href}"
    if href.startswith("/"):
        return FSAC_ORIGIN + href
    # bare file refs like tabs.html?page=x, contact.html, annonce.html#id
    return f"{FSAC_FRONT}{href}"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def maybe_json(value: Any, depth: int = 3) -> Any:
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


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html_lib.unescape(str(value)).replace("\xa0", " ")
    return _WS_PAT.sub(" ", text).strip()


def parse_date(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        ts = float(value)
        if ts > 1e12:  # epoch milliseconds
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ").split("+")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def fmt_display_date(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
              "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


def attachment_url(article_id: Any, filename: str) -> str:
    return f"{FSAC_ORIGIN}/Docs/attachments/{article_id}/{quote(str(filename))}"


def image_url(article_id: Any, img_name: Optional[str]) -> Optional[str]:
    if not img_name:
        return None
    return f"{FSAC_ORIGIN}/Docs/attachments/{article_id}/img/{quote(str(img_name))}"


def original_link(kind: str, item_id: Any, pos: int = 0) -> str:
    page = KIND_TO_PAGE.get(kind, "annonce.html")
    if kind == "recrut":
        return f"{FSAC_FRONT}{page}?p={int(pos or 0)}#{item_id}"
    return f"{FSAC_FRONT}{page}#{item_id}"


def proxy_url(absolute: str) -> str:
    """Route media through the local proxy so hotlink rules never bite."""
    from urllib.parse import quote as q
    return f"/api/proxy?url={q(absolute, safe='')}"


# ---------------------------------------------------------------------------
# sanitizer
# ---------------------------------------------------------------------------
def sanitize_html(raw: Optional[str], article_id: Any = None) -> str:
    """Allowlist-sanitize article HTML and rewrite FSAC media paths."""
    if not raw:
        return ""
    soup = BeautifulSoup(str(raw), "lxml")

    for bad in soup.find_all(["script", "style", "iframe", "object", "embed",
                              "form", "input", "button", "link", "meta",
                              "video", "audio", "source"]):
        bad.decompose()

    for tag in soup.find_all(True):
        name = tag.name.lower()
        if name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue
        keep = _ALLOWED_ATTRS.get(name, set())
        for attr in list(tag.attrs):
            if attr not in keep:
                del tag[attr]

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        href = _resolve_fsac_url(href, base="front")
        if not href.startswith(_SAFE_URL_SCHEMES):
            a["href"] = "#"
        else:
            a["href"] = href
        if href.startswith("http") and FSAC_ORIGIN.split("//")[-1] not in href[:80]:
            a["rel"] = "noopener noreferrer"
            a["target"] = "_blank"

    for img in soup.find_all("img", src=True):
        src = _resolve_fsac_url(img["src"].strip(), base="front")
        if src.startswith("data:"):
            pass  # inline data URIs are fine
        elif src.startswith("http"):
            img["src"] = proxy_url(src)
        else:
            img.decompose()
            continue
        img["loading"] = "lazy"
        img["referrerpolicy"] = "no-referrer"
        for attr in ("style", "onclick", "onerror", "target"):
            if attr in img.attrs:
                del img[attr]

    # Collapse empty paragraphs / stray whitespace text nodes
    for p in soup.find_all("p"):
        if not p.get_text(strip=True) and not p.find("img"):
            p.decompose()

    return str(soup).strip()


def excerpt_from_html(raw: Optional[str], limit: int = 220) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(str(raw), "lxml")
    text = clean_text(soup.get_text(" "))
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut + "…"


def count_attachments(raw: Any) -> int:
    data = maybe_json(raw)
    if isinstance(data, list):
        return len(data)
    return 0


# ---------------------------------------------------------------------------
# normalizers
# ---------------------------------------------------------------------------
def kind_of(raw: dict, fallback_group: str) -> str:
    t = str(raw.get("TYPE") or "").upper()
    if t in TYPE_TO_KIND:
        return TYPE_TO_KIND[t]
    if raw.get("step") is not None or "artTitle" in raw:
        return "recrut"
    return fallback_group


def normalize_list(items: Iterable[dict], fallback_group: str) -> list[dict]:
    """Normalize a WS list (annonces/events/actus groups) into feed items."""
    out: list[dict] = []
    seen: set[str] = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("ID") or raw.get("id") or "").strip()
        if not item_id:
            continue
        kind = kind_of(raw, fallback_group)
        title = clean_text(raw.get("TITLE") or raw.get("title") or raw.get("artTitle"))
        if not title:
            continue
        dt = parse_date(raw.get("DATE_PUBLICATION") or raw.get("DATE_EVENT") or raw.get("date"))
        text = raw.get("TEXT") or ""
        attachments = maybe_json(raw.get("ATTACHMENTS")) or []
        image = image_url(item_id, raw.get("IMG"))
        if not image and raw.get("IMG"):
            image = attachment_url(item_id, raw["IMG"])
        key = f"{kind}:{item_id}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": item_id,
            "kind": kind,
            "title": title,
            "subtitle": None,
            "date": dt.isoformat() if dt else None,
            "date_display": fmt_display_date(dt),
            "excerpt": excerpt_from_html(text),
            "image": image,
            "original_url": original_link(kind, item_id),
            "step": None,
            "attachment_count": len(attachments) if isinstance(attachments, list) else 0,
        })
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return out


def normalize_recrut_list(items: Iterable[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        rid = str(raw.get("id") or raw.get("ID") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        title = clean_text(raw.get("artTitle"))
        step = clean_text(raw.get("step")) or None
        subtitle = clean_text(raw.get("title")) or None
        if not title:
            continue
        dt = parse_date(raw.get("date"))
        label = "Avis de recrutement" if step == "avis" else (subtitle or step)
        out.append({
            "id": rid,
            "kind": "recrut",
            "title": title,
            "subtitle": subtitle if subtitle and subtitle != title else None,
            "date": dt.isoformat() if dt else None,
            "date_display": fmt_display_date(dt),
            "excerpt": clean_text(label) if label else "",
            "image": None,
            "original_url": original_link("recrut", rid, int(raw.get("pos") or 0)),
            "step": step,
            "attachment_count": 1,
        })
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return out


def normalize_article(detail: dict, fallback_kind: str = "annonce") -> dict:
    """Full article detail (WS `annonce&id=` / `actu&id=` / `recrut&id=`)."""
    if not isinstance(detail, dict):
        raise LookupError("empty article payload")
    item_id = str(detail.get("ID") or detail.get("id") or "").strip()
    if not item_id:
        raise LookupError("article payload missing ID")

    kind = kind_of(detail, fallback_kind)
    title = clean_text(detail.get("TITLE") or detail.get("artTitle"))
    dt = parse_date(detail.get("DATE_PUBLICATION") or detail.get("date"))
    text_html = detail.get("TEXT") or ""

    attachments: list[dict] = []
    raw_atts = maybe_json(detail.get("ATTACHMENTS"))
    if isinstance(raw_atts, list):
        for att in raw_atts:
            if not isinstance(att, dict):
                continue
            fname = str(att.get("file") or "").strip()
            if not fname:
                continue
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            attachments.append({
                "title": clean_text(att.get("title")) or fname,
                "url": attachment_url(item_id, fname),
                "ext": ext,
            })

    image = image_url(item_id, detail.get("IMG"))
    if not image and detail.get("IMG"):
        image = attachment_url(item_id, detail["IMG"])

    # recruitment steps arrive as RECRUT_DETAILS on RH articles
    recrut_details = maybe_json(detail.get("RECRUT_DETAILS"))
    if isinstance(recrut_details, list) and recrut_details and kind == "recrut":
        for d in recrut_details:
            if isinstance(d, dict) and d.get("doc"):
                fname = str(d["doc"])
                attachments.append({
                    "title": clean_text(d.get("title")) or fname,
                    "url": f"{FSAC_ORIGIN}/Docs/attachments/{item_id}/rh/{quote(fname)}",
                    "ext": fname.rsplit(".", 1)[-1].lower() if "." in fname else "",
                })
        if not dt and recrut_details[0].get("date"):
            dt = parse_date(recrut_details[0]["date"])

    before = detail.get("before") or {}
    after = detail.get("after") or {}
    prev_id = str(before.get("ID") or "") or None
    next_id = str(after.get("ID") or "") or None

    # Event poster (affiche)
    fiche = detail.get("FICHE_EVENT")
    if fiche:
        attachments.append({
            "title": "Affiche de l'événement",
            "url": f"{FSAC_ORIGIN}/Docs/attachments/{item_id}/affiche/{quote(str(fiche))}",
            "ext": "pdf",
        })

    html = sanitize_html(text_html, item_id)

    # TinyMCE content often repeats the title as a leading <h1>/<h2>: drop it.
    if html:
        try:
            frag = BeautifulSoup(html, "lxml")
            first = frag.find(["h1", "h2"])
            if first and clean_text(first.get_text()).casefold() == title.casefold():
                first.decompose()
                html = str(frag).strip()
        except Exception:
            pass

    step = None
    if kind == "recrut":
        raw_rec = maybe_json(detail.get("RECRUT_DETAILS"))
        if isinstance(raw_rec, list) and raw_rec and isinstance(raw_rec[0], dict):
            step = clean_text(raw_rec[0].get("step")) or "avis"

    return {
        "id": item_id,
        "kind": kind,
        "title": title,
        "subtitle": None,
        "date": dt.isoformat() if dt else None,
        "date_display": fmt_display_date(dt),
        "excerpt": excerpt_from_html(text_html),
        "image": image,
        "original_url": original_link(kind, item_id),
        "step": step,
        "attachment_count": len(attachments),
        "html": html,
        "attachments": attachments,
        "prev_id": prev_id,
        "next_id": next_id,
    }

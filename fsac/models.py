"""Pydantic response models for the wrapper API."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    title: str
    url: str
    ext: str = ""


class FeedItem(BaseModel):
    id: str
    kind: str  # annonce | event | actu | recrut
    title: str
    subtitle: Optional[str] = None
    date: Optional[str] = None  # ISO 8601
    date_display: Optional[str] = None
    excerpt: Optional[str] = ""
    image: Optional[str] = None
    original_url: str
    step: Optional[str] = None  # recrutements only (avis, ...)
    attachment_count: int = 0


class Article(FeedItem):
    html: str = ""
    attachments: List[Attachment] = Field(default_factory=list)
    prev_id: Optional[str] = None
    next_id: Optional[str] = None


class FeedResponse(BaseModel):
    items: List[FeedItem]
    fetched_at: str
    cached: bool = False
    counts: dict = Field(default_factory=dict)


class Stat(BaseModel):
    value: int
    label: str


class StatsResponse(BaseModel):
    stats: List[Stat]
    cached: bool = False
    source: str


class NavLink(BaseModel):
    title: str
    url: str
    extern: bool = False


class NavResponse(BaseModel):
    links: List[NavLink]
    cached: bool = False


class HealthResponse(BaseModel):
    status: str
    origin: str
    cache_ttl: int
    cache_entries: int
    server_time: str

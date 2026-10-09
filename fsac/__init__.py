"""FSAC wrapper package: client, normalization, models."""

from .client import FSACClient, get_client, init_client, close_client
from .normalize import (
    sanitize_html,
    excerpt_from_html,
    normalize_article,
    normalize_list,
    normalize_recrut_list,
    original_link,
)

__all__ = [
    "FSACClient",
    "get_client",
    "init_client",
    "close_client",
    "sanitize_html",
    "excerpt_from_html",
    "normalize_article",
    "normalize_list",
    "normalize_recrut_list",
    "original_link",
]

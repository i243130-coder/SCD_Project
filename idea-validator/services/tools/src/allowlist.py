"""Domain allow-list (ConfigMap `ALLOWED_DOMAINS`, comma separated)."""

from __future__ import annotations

import os
from urllib.parse import urlparse

DEFAULT = (
    "hacker-news.firebaseio.com,hn.algolia.com,api.github.com,api.producthunt.com,"
    "www.ycombinator.com,oauth.reddit.com,www.reddit.com"
)


def allowed_domains() -> set[str]:
    raw = os.environ.get("ALLOWED_DOMAINS", DEFAULT)
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def is_allowed(url: str, domains: set[str] | None = None) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    return p.hostname.lower() in (domains if domains is not None else allowed_domains())

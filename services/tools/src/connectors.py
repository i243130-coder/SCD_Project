"""Connectors: how each source is fetched (headers, auth). Tokens come from Secrets via env."""

from __future__ import annotations

import os

CONNECTORS: dict[str, dict[str, str]] = {
    "hn": {"accept": "application/json"},
    "hn_algolia": {"accept": "application/json"},
    "github": {"accept": "application/vnd.github+json", "token_env": "GITHUB_TOKEN", "auth": "Bearer"},
    "producthunt": {"accept": "application/json", "token_env": "PRODUCTHUNT_TOKEN", "auth": "Bearer"},
    "yc": {"accept": "application/json"},
    "reddit": {"accept": "application/json"},
    "generic": {"accept": "*/*"},
}


def headers_for(connector: str, user_agent: str) -> dict[str, str]:
    c = CONNECTORS.get(connector, CONNECTORS["generic"])
    h = {"User-Agent": user_agent, "Accept": c["accept"]}
    tok = os.environ.get(c.get("token_env", ""), "") if c.get("token_env") else ""
    if tok:
        h["Authorization"] = f"{c['auth']} {tok}"
    return h

"""Sanitiser: fetched web text is data, never instructions (rule 8).

Strips HTML/scripts/styles/hidden text, removes zero-width and control characters, and neutralises
instruction-like patterns aimed at models, replacing them with `[removed: possible instruction]`.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from ivcommon.injection import _COMPILED, REPLACEMENT, neutralise_text

_BLOCKS = re.compile(r"<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_HIDDEN = re.compile(
    r"<(\w+)\b[^>]*(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|hidden\b|aria-hidden=\"true\")"
    r"[^>]*>.*?</\1\s*>",
    re.I | re.S,
)
_COMMENTS = re.compile(r"<!--.*?-->", re.S)
_TAGS = re.compile(r"<[^>]+>")
_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class SanitiseResult:
    text: str
    injection_flags: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.injection_flags)


def strip_html(raw: str) -> str:
    t = _COMMENTS.sub(" ", raw)
    t = _BLOCKS.sub(" ", t)
    t = _HIDDEN.sub(" ", t)
    t = _TAGS.sub(" ", t)
    return html.unescape(t)


def sanitise(raw: str, *, is_html: bool | None = None) -> SanitiseResult:
    if is_html is None:
        is_html = bool(re.search(r"<[a-zA-Z!/][^>]*>", raw))
    t = strip_html(raw) if is_html else raw
    t = _ZERO_WIDTH.sub("", t)
    t = _CONTROL.sub(" ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t).strip()
    clean, flags = neutralise_text(t)
    res = SanitiseResult(text=clean, injection_flags=flags)
    # also flag patterns that only existed in markup/hidden text (removed above, but still an attack signal)
    raw_flags = [n for n, rx in _COMPILED.items() if rx.search(_ZERO_WIDTH.sub("", html.unescape(raw)))]
    res.injection_flags = res.injection_flags + [f for f in raw_flags if f not in res.injection_flags]
    return res


__all__ = ["REPLACEMENT", "SanitiseResult", "sanitise", "strip_html"]

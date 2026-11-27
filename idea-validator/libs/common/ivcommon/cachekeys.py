"""The single cache-key builder (R-M2). Keys include profile, rubric and engine versions."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

KINDS = {
    "verdict": (
        "idea_text",
        "profile_version",
        "profile_weights_version",
        "rubric_set_version",
        "engine_version",
        "kb_snapshot_id",
    ),
    "retrieval": ("query", "filters", "kb_snapshot_id"),
    "score": ("dimension", "idea_text", "evidence_ids", "rubric_version", "model"),
}


def normalise_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())


def cache_key(kind: str, **parts: Any) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown cache kind {kind}")
    required = KINDS[kind]
    missing = [p for p in required if p not in parts]
    if missing:
        raise ValueError(f"cache key {kind} missing parts {missing}")
    vals = []
    for p in required:
        v = parts[p]
        if p == "idea_text":
            v = normalise_text(str(v))
        if p == "evidence_ids":
            v = sorted(v)
        vals.append(json.dumps(v, sort_keys=True, default=str))
    digest = hashlib.sha256("|".join(vals).encode()).hexdigest()
    if kind == "score":
        return f"score:{parts['dimension']}:{digest}"
    return f"{kind}:{digest}"

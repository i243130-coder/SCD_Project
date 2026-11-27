"""M10 Scoring model server: POST /score. Output validated against DimensionScore;
invalid -> retry once -> fallback to the hosted model -> the fallback is logged (trace + metric)."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from ivcommon.health import health_router
from ivcommon.metrics import FALLBACKS, LATENCY, metrics_router
from ivcommon.schemas.core import DimensionScore, ScoreRequest

from .backends import Backend, GGUFBackend, HostedBackend, RuleBackend

log = logging.getLogger("scorer")
app = FastAPI(title="scorer (M10)")
RUBRICS_DIR = Path(os.environ.get("RUBRICS_DIR", str(Path(__file__).resolve().parents[3] / "rubrics")))


def primary() -> Backend:
    b = getattr(app.state, "primary", None)
    if b is None:
        kind = os.environ.get("SCORER_BACKEND", "rule")
        if kind == "gguf":
            b = GGUFBackend(
                os.environ.get("MODEL_PATH", "/models/scorer.gguf"),
                os.environ.get("SCORER_MODEL_NAME", "scorer-lora@v1"),
            )
        elif kind == "hosted":
            b = HostedBackend()
        else:
            b = RuleBackend()
        app.state.primary = b
    return b  # type: ignore[no-any-return]


def fallback() -> Backend:
    b = getattr(app.state, "fallback", None)
    if b is None:
        b = HostedBackend() if os.environ.get("HOSTED_MODEL") else RuleBackend()
        app.state.fallback = b
    return b  # type: ignore[no-any-return]


async def _ready() -> bool:
    return primary() is not None


app.include_router(health_router("scorer", {"model_loaded": _ready}))
app.include_router(metrics_router())


def rubric_text(rubric: str) -> str:
    name = rubric.replace("@", "@")
    p = RUBRICS_DIR / f"{name}.yaml"
    if not p.exists():
        raise HTTPException(422, f"unknown rubric {rubric}")
    data = yaml.safe_load(p.read_text())
    anchors = "\n".join(f"{k}: {v}" for k, v in sorted(data["anchors"].items(), reverse=True))
    rules = "\n".join(f"- {r}" for r in data.get("rules", []))
    return f"{anchors}\nRules:\n{rules}"


def parse(raw: str, req: ScoreRequest, model: str) -> DimensionScore:
    data: Any = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    allowed = {e.evidence_id for e in req.evidence}
    ids = [i for i in data.get("evidence_ids") or [] if i in allowed]  # drop invented ids
    score = data.get("score")
    abstained = score is None or not ids
    return DimensionScore(
        dimension=req.dimension,
        score=float(score) if score is not None and not abstained else None,
        confidence=0.0 if abstained else float(data["confidence"] if data.get("confidence") is not None else 0.5),
        evidence_ids=ids,
        features=req.features,
        reason=str(data.get("reason", ""))[:600],
        rubric_version=req.rubric,
        model=model,
        abstained=abstained,
        extra=data.get("extra") or {},
    )


@app.post("/score", response_model=DimensionScore)
async def score(req: ScoreRequest) -> DimensionScore:
    rt = rubric_text(req.rubric)
    t0 = time.perf_counter()
    p = primary()
    for attempt in (1, 2):  # first try + one retry
        try:
            raw, _ = await p.generate(req, rt)
            out = parse(raw, req, p.name)
            LATENCY.labels(f"scorer_{p.name}").observe(time.perf_counter() - t0)
            return out
        except (ValueError, ValidationError, json.JSONDecodeError, KeyError, TypeError) as e:
            log.warning("scorer invalid output (attempt %s): %r", attempt, e)
    fb = fallback()
    FALLBACKS.labels(req.dimension).inc()
    log.warning(json.dumps({"event": "scorer_fallback", "dimension": req.dimension, "from": p.name, "to": fb.name}))
    try:
        raw, _ = await fb.generate(req, rt)
        out = parse(raw, req, fb.name)
        out.extra = {**out.extra, "fallback": True}
        return out
    except (ValueError, ValidationError, json.JSONDecodeError, KeyError, TypeError) as e:
        return DimensionScore(
            dimension=req.dimension,
            score=None,
            confidence=0.0,
            evidence_ids=[],
            reason=f"invalid output from primary and fallback: {e!r}",
            rubric_version=req.rubric,
            model=fb.name,
            abstained=True,
            extra={"fallback": True},
        )

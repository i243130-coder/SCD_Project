"""M11 Verdict service: POST /verdict, POST /whatif. Plain code, no language model."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from ivcommon.health import health_router
from ivcommon.metrics import metrics_router
from ivcommon.schemas.core import Verdict, VerdictRequest, WhatIfRequest

from .config import load_config
from .engine import decide, whatif

CONFIG = load_config()  # refuses to start if a preset does not sum to 100

app = FastAPI(title="verdict (M11)")
app.include_router(health_router("verdict"))
app.include_router(metrics_router())


@app.post("/verdict", response_model=Verdict)
async def post_verdict(req: VerdictRequest) -> Verdict:
    try:
        return decide(req, CONFIG)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/whatif", response_model=Verdict)
async def post_whatif(req: WhatIfRequest) -> Verdict:
    try:
        return whatif(req, CONFIG)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/config")
async def get_config() -> dict[str, object]:
    return CONFIG.model_dump()

"""M12 Critic & Guardrails: /check, /input_rail, /sanitize_check, /approval_needed."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from ivcommon.config import get_settings
from ivcommon.health import health_router
from ivcommon.http import post_json
from ivcommon.injection import detect, neutralise_text
from ivcommon.llm import LLMClient
from ivcommon.metrics import INJECTIONS, metrics_router
from ivcommon.schemas.core import Claim, ClaimCheck

from .approval import ApprovalAnswer, ApprovalQuery, approval_needed
from .claims import check_claim
from .input_rail import RailResult, check_input

app = FastAPI(title="critic (M12)")
app.include_router(health_router("critic"))
app.include_router(metrics_router())


class CheckRequest(BaseModel):
    claims: list[Claim]


class TextBody(BaseModel):
    text: str


async def kb_lookup(ids: list[str]) -> dict[str, str]:
    data: Any = await post_json(f"{get_settings().kb_url}/evidence/lookup", {"ids": ids}, timeout_s=5)
    return {k: v for k, v in data.get("found", {}).items()}


def _llm() -> LLMClient:
    if getattr(app.state, "llm", None) is None:
        app.state.llm = LLMClient()
    return app.state.llm


def _lookup() -> Any:
    return getattr(app.state, "lookup", None) or kb_lookup


@app.post("/check", response_model=list[ClaimCheck])
async def check(req: CheckRequest) -> list[ClaimCheck]:
    return list(await asyncio.gather(*(check_claim(c, _lookup(), _llm()) for c in req.claims)))


@app.post("/input_rail", response_model=RailResult)
async def input_rail(body: TextBody) -> RailResult:
    res = check_input(body.text)
    if res.decision == "block" and res.flags:
        INJECTIONS.labels("input_rail").inc()
    return res


@app.post("/sanitize_check")
async def sanitize_check(body: TextBody) -> dict[str, Any]:
    text, flags = neutralise_text(body.text)
    if flags:
        INJECTIONS.labels("critic").inc(len(flags))
    return {"text": text, "injection_flags": flags, "flagged": bool(detect(body.text))}


@app.post("/approval_needed", response_model=ApprovalAnswer)
async def post_approval_needed(q: ApprovalQuery) -> ApprovalAnswer:
    return approval_needed(q)

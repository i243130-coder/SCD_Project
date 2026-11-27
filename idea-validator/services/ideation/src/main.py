"""M8 Idea Generator agents: /generate (Ideator), /gap_analyse, /skeptic, /suggest_change, /extract."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from ivcommon.config import get_settings
from ivcommon.health import health_router
from ivcommon.llm import LLMClient
from ivcommon.metrics import metrics_router
from ivcommon.schemas.core import GeneratedIdea, Objection

from .agents import ask_json, extract_fields_rule, llm_enabled, novelty_ok, suggest_change_rule, template_ideas

app = FastAPI(title="ideation (M8)")
app.include_router(health_router("ideation"))
app.include_router(metrics_router())


def llm() -> LLMClient:
    if getattr(app.state, "llm", None) is None:
        app.state.llm = LLMClient(fixtures_dir="/fixtures/llm")
    return app.state.llm  # type: ignore[no-any-return]


async def kb_search(query: str, k: int = 5) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{get_settings().kb_url}/search", json={"query": query, "k": k})
            r.raise_for_status()
            return r.json()["results"]  # type: ignore[no-any-return]
    except httpx.HTTPError:
        return []


@app.post("/generate")
async def generate(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (await ask_json(llm(), "ideator", payload))["ideas"] if llm_enabled() else template_ideas(payload)
    launched = [e["quote"] for i in raw for e in await kb_search(i["title"], 3) if e["source"] in ("producthunt", "yc")]
    out = []
    for idea in raw:
        try:
            GeneratedIdea.model_validate({**idea, "source": "generated"})  # >= 1 gap evidence id
        except ValueError:
            continue
        if novelty_ok(idea, launched):
            out.append(idea)
    return out


@app.post("/gap_analyse")
async def gap_analyse(idea: dict[str, Any]) -> dict[str, Any]:
    ev = await kb_search(f"complaints missing features {idea['title']} {idea.get('problem', '')}", 5)
    complaints = [e["quote"] for e in ev if e["source"] in ("hackernews", "reddit")]
    return {**idea, "complaints": complaints[:3], "extra_evidence_ids": [e["evidence_id"] for e in ev]}


@app.post("/skeptic", response_model=list[Objection])
async def skeptic(payload: dict[str, Any]) -> list[Objection]:
    if llm_enabled():
        data = await ask_json(llm(), "skeptic", payload)
        return [Objection.model_validate(o) for o in data.get("objections", data if isinstance(data, list) else [])]
    idea = payload["idea"]
    ev = await kb_search(f"{idea.get('title', '')} {idea.get('text', '')}", 5)
    out = []
    for e in ev:
        if e["source"] in ("producthunt", "yc"):
            out.append(
                Objection(
                    dimension="competition",
                    text=f"An existing product covers this: {e['quote'][:120]}",
                    evidence_ids=[e["evidence_id"]],
                    fatal=False,
                )
            )
    return out[:3]


class SuggestIn(BaseModel):
    idea: str = ""
    dimension: str | None = None
    delta: float = 0
    change: str = ""


@app.post("/suggest_change")
async def suggest_change(p: SuggestIn) -> dict[str, str]:
    if llm_enabled():
        return {"change": str((await ask_json(llm(), "suggest_change", p.model_dump()))["change"])}
    return {"change": f"{suggest_change_rule(p.model_dump())} ({p.change})"}


class ExtractIn(BaseModel):
    text: str


@app.post("/extract")
async def extract(b: ExtractIn) -> dict[str, Any]:
    if llm_enabled():
        return await ask_json(llm(), "extract_fields", {"idea": b.text})  # type: ignore[no-any-return]
    return extract_fields_rule(b.text)

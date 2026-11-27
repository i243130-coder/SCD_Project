"""Scoring backends. All return raw text that must parse to {score, confidence, evidence_ids, reason, extra?}.

* gguf   - the fine-tuned 1.5B model (llama-cpp-python, grammar/JSON-constrained), file from MODEL_URL
* hosted - an OpenAI-compatible hosted model (also the fallback)
* rule   - deterministic heuristic from computed features (walking skeleton / no keys / CI)
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from ivcommon.llm import DATA_SYSTEM_LINE, LLMClient, data_block
from ivcommon.schemas.core import ScoreRequest


class Backend(Protocol):
    name: str

    async def generate(self, req: ScoreRequest, rubric_text: str) -> tuple[str, dict[str, Any]]: ...


def build_messages(req: ScoreRequest, rubric_text: str) -> list[dict[str, str]]:
    ev = "\n".join(f"[{e.evidence_id}] ({e.source}) {e.quote}" for e in req.evidence)
    feats = json.dumps(req.features, sort_keys=True)
    return [
        {
            "role": "system",
            "content": f"Score the idea on {req.dimension} using rubric {req.rubric}. {DATA_SYSTEM_LINE} "
            "Cite only evidence ids given in EVIDENCE; if none support a score, reply with "
            '"score": null. Reply with JSON only: {"score": 0-5 or null, "confidence": 0-1, '
            '"evidence_ids": [...], "reason": "...", "extra": {}}\n\nRUBRIC:\n' + rubric_text,
        },
        {
            "role": "user",
            "content": f"IDEA: {data_block(req.idea.text)}\nFEATURES: {feats}\nEVIDENCE:\n{data_block(ev)}",
        },
    ]


class HostedBackend:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.name = f"hosted:{self.llm.model}"

    async def generate(self, req: ScoreRequest, rubric_text: str) -> tuple[str, dict[str, Any]]:
        r = await self.llm.chat(build_messages(req, rubric_text), max_tokens=400)
        return r.content, {"tokens_in": r.tokens_in, "tokens_out": r.tokens_out, "cost_usd": r.cost_usd}


class GGUFBackend:
    def __init__(self, path: str, name: str) -> None:
        from llama_cpp import Llama  # optional heavy dependency, only in the scorer image

        self.m = Llama(model_path=path, n_ctx=2048, n_threads=int(os.environ.get("SCORER_THREADS", "2")), verbose=False)
        self.name = name

    async def generate(self, req: ScoreRequest, rubric_text: str) -> tuple[str, dict[str, Any]]:
        out = self.m.create_chat_completion(
            messages=build_messages(req, rubric_text),  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=300,
        )
        return out["choices"][0]["message"]["content"], {
            "tokens_in": out["usage"]["prompt_tokens"],  # type: ignore[index]
            "tokens_out": out["usage"]["completion_tokens"],
            "cost_usd": 0.0,
        }  # type: ignore[index]


class RuleBackend:
    """Transparent heuristic used when no model is configured. It only uses computed features."""

    name = "rule"

    async def generate(self, req: ScoreRequest, rubric_text: str) -> tuple[str, dict[str, Any]]:
        f, ids = req.features, [e.evidence_id for e in req.evidence][:3]
        d = req.dimension
        if not ids:
            return json.dumps({"score": None, "confidence": 0, "evidence_ids": [], "reason": "no evidence"}), {}
        if d == "demand_pain":
            s = min(
                5.0,
                1.0
                + 0.6 * f.get("n_sources", 0)
                + 0.3 * f.get("complaint_count", 0)
                + (0.5 if f.get("trend_growth", 0) > 0.05 else 0),
            )
        elif d == "competition":
            s = max(0.0, 4.5 - 0.8 * f.get("n_direct_competitors", 0) - 0.7 * f.get("funded_competitors", 0))
        elif d == "differentiation":
            s = max(
                0.0,
                min(
                    5.0, 5.0 * (1 - f.get("max_similarity_to_existing", 0.5)) + 0.5 * f.get("unaddressed_gap_count", 0)
                ),
            )
        elif d == "feasibility":
            ratio = f.get("available_hours", 0) / max(1.0, f.get("effort_hours", 1))
            s = max(0.0, min(5.0, 1.5 * ratio + 2.0 * f.get("skill_overlap", 0)))
        elif d == "risk":
            s = max(0.0, 5.0 - 1.5 * f.get("risk_flags", 0))
        else:
            s = max(0.0, min(5.0, 2.0 + 3.0 * f.get("interest_overlap", 0) + f.get("novelty", 0)))
        s = round(s * 2) / 2
        conf = round(min(0.9, 0.4 + 0.1 * len(ids)), 2)
        return json.dumps(
            {
                "score": s,
                "confidence": conf,
                "evidence_ids": ids,
                "reason": f"rule-based {d} score from computed features",
            }
        ), {}

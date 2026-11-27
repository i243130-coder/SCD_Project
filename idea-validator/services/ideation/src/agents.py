"""M8 agents. With an LLM configured (HOSTED_MODEL, or LLM_MODE=replay) they use the versioned prompts in
prompts/*.md; otherwise a transparent template fallback keeps the system usable (model="template")."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ivcommon.llm import DATA_SYSTEM_LINE, LLMClient, data_block

PROMPTS = Path(os.environ.get("PROMPTS_DIR", str(Path(__file__).resolve().parents[3] / "prompts")))


def prompt(name: str) -> str:
    text = (PROMPTS / f"{name}@v1.md").read_text()
    return text.split("---", 2)[-1].strip()


def llm_enabled() -> bool:
    return bool(os.environ.get("HOSTED_MODEL")) or os.environ.get("LLM_MODE") == "replay"


async def ask_json(llm: LLMClient, name: str, payload: dict[str, Any]) -> Any:
    msgs = [
        {"role": "system", "content": f"{prompt(name)}\n{DATA_SYSTEM_LINE}"},
        {"role": "user", "content": data_block(json.dumps(payload, default=str))},
    ]
    r = await llm.chat(msgs)
    return json.loads(r.content)


def _sim(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-z0-9]{3,}", a.lower()))
    tb = set(re.findall(r"[a-z0-9]{3,}", b.lower()))
    return len(ta & tb) / max(1, len(ta | tb))


def novelty_ok(idea: dict[str, Any], launched_names: list[str], threshold: float = 0.9) -> bool:
    """Reject renamed copies of existing products."""
    t = f"{idea['title']} {idea.get('one_liner', '')}"
    return all(_sim(t, n) <= threshold for n in launched_names)


def template_ideas(payload: dict[str, Any]) -> list[dict[str, Any]]:
    gaps = payload.get("gaps") or []
    out = []
    for i, g in enumerate(gaps[: payload.get("count", 8)]):
        desc = g["description"].rstrip(".")
        out.append(
            {
                "title": f"Focused tool: {desc[:60]}",
                "one_liner": f"A small web tool that solves: {desc}",
                "problem": desc,
                "customer": "the people raising this complaint",
                "niche_id": g.get("niche_id"),
                "gap_evidence_ids": g["evidence_ids"][:2],
                "id": f"t{payload.get('round', 1)}_{i}",
            }
        )
    for r in payload.get("revise") or []:
        out.append(
            {
                **{k: v for k, v in r.items() if k != "objections"},
                "one_liner": r.get("one_liner", "") + " (narrowed to a single first customer segment)",
            }
        )
    return out


def extract_fields_rule(text: str) -> dict[str, Any]:
    low = text.lower()
    platform = (
        "mobile"
        if re.search(r"\b(mobile|android|ios)\b", low)
        else "web"
        if re.search(r"\b(web|website|browser)\b", low)
        else None
    )
    customer = re.search(r"\bfor ([a-z][a-z \-]{3,40})", low)
    scope = re.search(r"\b(mvp|one feature|single feature|small|full platform|end-to-end)\b", low)
    feats = re.search(r"\b(features?|lets? (users|you)) ([^.]{5,80})", low)
    return {
        "customer": customer.group(1).strip() if customer else None,
        "platform": platform,
        "scope": scope.group(1) if scope else None,
        "core_features": feats.group(3).strip() if feats else None,
    }


def suggest_change_rule(p: dict[str, Any]) -> str:
    hints = {
        "demand_pain": "Target the group with the most documented complaints and validate with 5 of them first",
        "competition": "Narrow to one underserved segment the funded competitors ignore",
        "differentiation": "Build around the unaddressed complaint that existing products miss",
        "feasibility": "Cut the first version to one core feature on web only",
        "risk": "Remove the feature that touches sensitive data or a single platform's API",
        "learning": "Add one component that teaches a skill you want (e.g. a small ML model)",
    }
    return hints.get(p.get("dimension") or "", p.get("change", "Narrow the scope of the first version"))

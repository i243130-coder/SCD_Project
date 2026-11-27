"""Shared helpers for the fine-tuning pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DIMS = ["demand_pain", "competition", "differentiation", "feasibility", "risk", "learning"]


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def labelled_ideas(path: Path | None = None) -> set[str]:
    p = path or ROOT / "eval/labelled/ideas.yaml"
    if not p.exists():
        return set()
    return {norm(i["idea"]) for i in (yaml.safe_load(p.read_text()) or {}).get("ideas", [])}


def read_jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


def write_jsonl(p: Path, rows: list[dict[str, Any]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def to_chat(ex: dict[str, Any]) -> dict[str, Any]:
    ev = " ".join(f"[{e['evidence_id']}] {e['quote']}" for e in ex["evidence"])
    label = ex["label"]
    return {
        "messages": [
            {
                "role": "system",
                "content": f"Score the idea on {ex['dimension']} using rubric {ex['dimension']}@v1. Reply with JSON only.",
            },
            {"role": "user", "content": f"IDEA: {ex['idea']} EVIDENCE: {ev}"},
            {
                "role": "assistant",
                "content": json.dumps({k: label[k] for k in ("score", "confidence", "evidence_ids", "reason")}),
            },
        ],
        "idea_id": ex["idea_id"],
        "dimension": ex["dimension"],
    }

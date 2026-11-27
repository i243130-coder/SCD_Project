"""Replay a run from its stored trace (R-G12): LLM_MODE=replay, tool results served from the trace, no network.

    python scripts/replay_run.py --trace traces/run_90.jsonl

Re-drives the orchestrator's Validate machine with agents whose answers come from the recorded tool outputs, then
diffs the sequence of state decisions with the original run. Exit code 1 if the decisions differ."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
os.environ["LLM_MODE"] = "replay"
sys.path.insert(0, str(ROOT / "services" / "orchestrator"))

from ivcommon.schemas.core import DimensionScore, EvidenceItem, Objection, StudentProfile, Verdict  # noqa: E402
from ivcommon.tracing import Tracer  # noqa: E402
from src.machines.validate import ValidateContext, ValidateMachine  # noqa: E402


class ReplayAgents:
    def __init__(self, records: list[dict[str, Any]], profile: dict[str, Any]) -> None:
        self.out: dict[str, list[Any]] = defaultdict(list)
        for r in records:
            if r["kind"] != "decision" or r["agent"] == "verdict_engine":
                try:
                    self.out[r["agent"]].append(json.loads(r["output"]))
                except (ValueError, TypeError):
                    self.out[r["agent"]].append(r["output"])
        self.profile = profile

    def _next(self, agent: str) -> Any:
        if not self.out[agent]:
            raise RuntimeError(f"trace has no more recorded outputs for {agent}")
        return self.out[agent].pop(0)

    async def input_rail(self, text: str) -> Any:
        return self._next("input_rail")

    async def get_profile(self, uid: str) -> StudentProfile:
        return StudentProfile.model_validate(self._next("profile"))

    async def create_idea(self, *a: Any) -> Any:
        return self._next("create_idea")

    async def cache_get(self, key: str) -> Any:
        return None

    async def cache_put(self, *a: Any) -> None:
        return None

    async def extract_fields(self, t: str) -> Any:
        return self._next("extract_fields")

    async def whatif(self, payload: dict[str, Any]) -> Verdict:
        raise RuntimeError("clarify whatif calls are not traced; replay with skip_clarify")

    async def search(self, q: str, k: int = 10, filters: Any = None) -> list[EvidenceItem]:
        return [EvidenceItem.model_validate(e) for e in self._next("kb_search")]

    async def scout(self, *a: Any) -> Any:
        return self._next("scout_on_demand")

    async def score(self, scorer: str, payload: Any, run_id: str) -> list[DimensionScore]:
        return [DimensionScore.model_validate(s) for s in self._next(f"{scorer}_scorer")]

    async def verdict(self, payload: Any) -> Verdict:
        return Verdict.model_validate(self._next("verdict_engine"))

    async def skeptic(self, payload: Any) -> list[Objection]:
        return [Objection.model_validate(o) for o in self._next("skeptic")]

    async def check_claims(self, claims: Any) -> Any:
        return self._next("critic_check")

    async def suggest_change(self, p: Any) -> str:
        return str(self._next("suggest_change"))

    async def save_verdict(self, v: Any) -> None:
        return None

    async def persist_run(self, *a: Any) -> None:
        return None

    async def publish(self, *a: Any) -> None:
        return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--idea-text", default="(replayed)")
    a = ap.parse_args()
    recs = [json.loads(line) for line in Path(a.trace).read_text().splitlines() if line.strip()]
    original = [
        f"{r['input']}->{r['output']}" for r in recs if r["kind"] == "decision" and r["agent"] == "orchestrator"
    ]
    agents = ReplayAgents(recs, {})
    ctx = ValidateContext(
        run_id=recs[0]["run_id"] + "-replay",
        user_id="replay",
        idea_text=a.idea_text,
        skip_clarify=not any(r["agent"] == "extract_fields" for r in recs),
    )
    m = ValidateMachine(ctx, agents, tracer=Tracer(ctx.run_id, send=False, echo=False))  # type: ignore[arg-type]
    await m.run()
    replayed = [
        f"{r.input}->{r.output}" for r in m.tracer.records if r.kind == "decision" and r.agent == "orchestrator"
    ]
    same = original == replayed
    print(json.dumps({"original": original, "replayed": replayed, "identical": same}, indent=2))
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

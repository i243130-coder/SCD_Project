"""Trace store: traces/{run_id}.jsonl on a PVC + a tree view (parent_step)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ivcommon.schemas.core import TraceRecord


class TraceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, run_id: str) -> Path:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
        return self.root / f"{safe}.jsonl"

    def append(self, recs: list[TraceRecord]) -> int:
        by: dict[str, list[TraceRecord]] = {}
        for r in recs:
            by.setdefault(r.run_id, []).append(r)
        for run, rs in by.items():
            with self.path(run).open("a") as f:
                for r in rs:
                    f.write(r.model_dump_json() + "\n")
        return len(recs)

    def read(self, run_id: str) -> list[TraceRecord]:
        p = self.path(run_id)
        if not p.exists():
            return []
        return [TraceRecord.model_validate_json(line) for line in p.read_text().splitlines() if line.strip()]

    def summary(self, run_id: str) -> dict[str, Any]:
        rs = self.read(run_id)
        return {
            "run_id": run_id,
            "n_steps": len(rs),
            "cost_usd": round(sum(r.cost_usd for r in rs), 6),
            "latency_ms": sum(r.latency_ms for r in rs),
            "cache_hits": sum(r.cache_hit for r in rs),
            "errors": sum(1 for r in rs if r.error),
            "decisions": [f"{r.input}->{r.output}" for r in rs if r.kind == "decision" and r.agent == "orchestrator"],
        }

    def tree(self, run_id: str) -> list[dict[str, Any]]:
        rs = self.read(run_id)
        nodes = {r.step_id: {**json.loads(r.model_dump_json()), "children": []} for r in rs}
        roots = []
        for r in rs:
            if r.parent_step and r.parent_step in nodes:
                nodes[r.parent_step]["children"].append(nodes[r.step_id])
            else:
                roots.append(nodes[r.step_id])
        return roots

    def runs(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.jsonl"))

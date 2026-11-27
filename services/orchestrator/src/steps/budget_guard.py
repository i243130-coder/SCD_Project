"""BudgetGuard: tracks tokens/pages/steps/cost per run; decides when the user must approve (U4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ivcommon.budget import Budget, BudgetState


def _config_path() -> Path:
    for p in (Path("/config/budgets.yaml"), Path(__file__).resolve().parents[4] / "config" / "budgets.yaml"):
        if p.exists():
            return p
    raise FileNotFoundError("budgets.yaml")


def load_budget_config(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or _config_path()).read_text())


@dataclass
class ApprovalNeeded:
    action: str
    estimated_cost_usd: float
    current_spend: float
    budget_usd: float
    message: str


class BudgetGuard:
    def __init__(self, kind: str, cfg: dict[str, Any] | None = None, state: dict[str, Any] | None = None) -> None:
        cfg = cfg or load_budget_config()
        self.estimates: dict[str, float] = cfg.get("estimates", {})
        self.template: str = cfg.get("approval", {}).get("message", "cost ${estimate:.3f}")
        self.state = BudgetState(Budget(**cfg["runs"][kind]))
        if state:
            self.state.add(
                tokens=state.get("tokens", 0),
                pages=state.get("pages", 0),
                steps=state.get("steps", 0),
                cost_usd=state.get("cost_usd", 0.0),
            )

    def estimate(self, action: str) -> float:
        return float(self.estimates.get(action, 0.0))

    def check(self, action: str, estimate: float | None = None) -> ApprovalNeeded | None:
        est = self.estimate(action) if estimate is None else estimate
        if not self.state.would_exceed(cost_usd=est):
            return None
        b = self.state.budget.max_cost_usd
        return ApprovalNeeded(
            action, est, self.state.cost_usd, b, self.template.format(estimate=est, spent=self.state.cost_usd, budget=b)
        )

    def spend(self, *, cost_usd: float = 0.0, tokens: int = 0, pages: int = 0, steps: int = 1) -> None:
        self.state.add(cost_usd=cost_usd, tokens=tokens, pages=pages, steps=steps)

    def snapshot(self) -> dict[str, Any]:
        return self.state.snapshot()

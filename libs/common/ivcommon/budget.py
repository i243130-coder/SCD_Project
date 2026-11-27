"""Budget accounting (tokens, pages, steps, cost) shared by M3 and M5."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Budget:
    max_tokens: int = 80_000
    max_pages: int = 30
    max_steps: int = 120
    max_cost_usd: float = 0.05


@dataclass
class BudgetState:
    budget: Budget
    tokens: int = 0
    pages: int = 0
    steps: int = 0
    cost_usd: float = 0.0
    log: list[dict[str, Any]] = field(default_factory=list)

    def add(self, *, tokens: int = 0, pages: int = 0, steps: int = 0, cost_usd: float = 0.0) -> None:
        self.tokens += tokens
        self.pages += pages
        self.steps += steps
        self.cost_usd += cost_usd

    def would_exceed(self, *, tokens: int = 0, pages: int = 0, steps: int = 0, cost_usd: float = 0.0) -> list[str]:
        over = []
        if self.tokens + tokens > self.budget.max_tokens:
            over.append("tokens")
        if self.pages + pages > self.budget.max_pages:
            over.append("pages")
        if self.steps + steps > self.budget.max_steps:
            over.append("steps")
        if self.cost_usd + cost_usd > self.budget.max_cost_usd + 1e-12:
            over.append("cost")
        return over

    def snapshot(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "pages": self.pages,
            "steps": self.steps,
            "cost_usd": round(self.cost_usd, 6),
            "max_cost_usd": self.budget.max_cost_usd,
            "max_tokens": self.budget.max_tokens,
        }


def load_budgets(path: str | Path) -> dict[str, Budget]:
    data = yaml.safe_load(Path(path).read_text())
    return {kind: Budget(**vals) for kind, vals in data["runs"].items()}

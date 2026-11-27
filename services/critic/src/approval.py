"""Approval-above-budget policy, kept in one place (config/budgets.yaml)."""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_MSG = "This step will cost about ${estimate:.3f} (spent ${spent:.3f} of ${budget:.3f}). Approve?"


class ApprovalQuery(BaseModel):
    spent: float
    estimate: float
    budget: float
    action: str = "deep_search"


class ApprovalAnswer(BaseModel):
    needed: bool
    message: str


def approval_needed(q: ApprovalQuery, template: str = DEFAULT_MSG) -> ApprovalAnswer:
    needed = q.spent + q.estimate > q.budget + 1e-12
    msg = template.format(estimate=q.estimate, spent=q.spent, budget=q.budget) if needed else "within budget"
    return ApprovalAnswer(needed=needed, message=msg)

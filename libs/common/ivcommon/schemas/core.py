"""All shared data schemas (Section 5). Field lists are minimums."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Source = Literal["hackernews", "github", "producthunt", "yc", "reddit"]
Dimension = Literal["demand_pain", "competition", "differentiation", "feasibility", "risk", "learning"]
DIMENSIONS: tuple[Dimension, ...] = (
    "demand_pain",
    "competition",
    "differentiation",
    "feasibility",
    "risk",
    "learning",
)
VerdictLabel = Literal["GO", "PIVOT", "NO-GO", "INSUFFICIENT_EVIDENCE"]
Goal = Literal["startup", "portfolio", "course_project"]
Stability = Literal["STABLE", "BORDERLINE"]
GateName = Literal["evidence", "feasibility", "risk", "duplicate"]
GateStatus = Literal["pass", "fail", "not_run"]


class IdeaCard(BaseModel):
    id: str
    name: str
    summary: str
    problem: str = ""
    customer: str = ""
    niche_tags: list[str] = []
    stage: Literal["launched", "seed", "series_a", "growth", "acquired", "dead", "unknown"] = "unknown"
    funding_usd: int | None = None
    source: Source
    url: str
    published_at: date | None = None
    fetched_at: datetime
    text: str


class StudentProfile(BaseModel):
    user_id: str
    skills: list[str]
    hours_per_week: float = Field(ge=0, le=80)
    weeks_available: int = Field(ge=1, le=52)
    team_size: int = Field(ge=1, le=6)
    compute: Literal["laptop", "free_gpu", "paid"]
    goal: Goal
    interests: list[str] = []
    profile_version: int = 1

    @property
    def available_hours(self) -> float:
        return self.hours_per_week * self.weeks_available * self.team_size


class EvidenceItem(BaseModel):
    evidence_id: str
    card_id: str
    quote: str
    source: Source
    url: str
    retrieved_at: datetime
    published_at: date | None = None


class DimensionScore(BaseModel):
    dimension: Dimension
    score: float | None = Field(default=None, ge=0, le=5)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    features: dict[str, float] = {}
    reason: str
    rubric_version: str
    model: str
    abstained: bool = False
    extra: dict[str, Any] = {}
    cache_hit: bool = False


class WhatIfOption(BaseModel):
    change: str
    dimension: Dimension | None = None
    delta: float = 0
    new_score: float
    new_verdict: VerdictLabel
    new_stability: Stability


class Flip(BaseModel):
    perturbation: str
    verdict: VerdictLabel
    score: float | None


class Verdict(BaseModel):
    idea_id: str
    version: int
    run_id: str
    verdict: VerdictLabel
    stability: Stability
    score: float | None
    confidence: float
    gates: dict[GateName, GateStatus]
    gate_details: dict[str, str] = {}
    weights: dict[Dimension, float]
    thresholds: dict[str, float]
    scores: list[DimensionScore]
    weakest_dimension: Dimension | None
    missing: list[str] = []
    what_would_make_go: list[WhatIfOption] = []
    sensitivity: dict[str, Any]
    versions: dict[str, str]
    cache_hit: bool = False


class TraceRecord(BaseModel):
    run_id: str
    step_id: int
    parent_step: int | None
    agent: str
    kind: Literal["tool_call", "llm_call", "decision"]
    tool: str | None = None
    input: str
    output: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    retries: int = 0
    model: str | None = None
    cache_hit: bool = False
    error: str | None = None
    ts: datetime


RunEventType = Literal[
    "state", "agent_start", "agent_end", "tool_call", "spend", "question", "approval_required", "result", "error"
]


class RunEvent(BaseModel):
    type: RunEventType
    run_id: str
    ts: datetime
    payload: dict[str, Any] = {}


class Claim(BaseModel):
    text: str
    evidence_ids: list[str]


class ClaimCheck(BaseModel):
    text: str
    supported: bool
    reason: str
    similarity: float | None = None


class Objection(BaseModel):
    dimension: Dimension
    text: str
    evidence_ids: list[str]
    fatal: bool = False


class GeneratedIdea(BaseModel):
    title: str
    one_liner: str
    problem: str
    customer: str
    niche_id: str | None = None
    gap_evidence_ids: list[str] = Field(min_length=1)
    source: Literal["generated"] = "generated"


class Niche(BaseModel):
    id: str
    name: str
    size: int
    trend_slope: float
    status: Literal["rising", "flat", "saturated"]
    keywords: list[str] = []


class Gap(BaseModel):
    id: str
    niche_id: str
    description: str
    evidence_ids: list[str]


class IdeaInput(BaseModel):
    title: str = ""
    text: str = Field(min_length=1, max_length=2000)


class ScoreRequest(BaseModel):
    rubric: str
    dimension: Dimension
    idea: IdeaInput
    evidence: list[EvidenceItem]
    profile: StudentProfile | None = None
    features: dict[str, float] = {}


class ChallengeAdjustment(BaseModel):
    dimension: Dimension
    accepted_objections: int = Field(ge=0)


class VerdictRequest(BaseModel):
    idea_id: str = "adhoc"
    version: int = 1
    run_id: str = "adhoc"
    scores: list[DimensionScore]
    profile: StudentProfile
    n_sources: int = Field(ge=0)
    n_platforms: int = Field(ge=0)
    config_override: dict[str, Any] | None = None
    challenge_adjustments: list[ChallengeAdjustment] = []
    rubric_set_version: str = "r1"
    include_what_if: bool = True


class WhatIfRequest(VerdictRequest):
    score_overrides: dict[Dimension, float] = {}
    weight_overrides: dict[Dimension, float] | None = None
    profile_overrides: dict[str, Any] = {}

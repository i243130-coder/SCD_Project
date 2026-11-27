"""Discover workflow (Section 10.2): niches -> Ideator / Gap Analyst / Skeptic / Critic debate (<= 3 rounds)
-> validate survivors (concurrency 3, shared budget) -> rank."""

from __future__ import annotations

import asyncio
import enum
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from ivcommon.metrics import APPROVALS
from ivcommon.schemas.core import StudentProfile, Verdict
from ivcommon.tracing import Tracer

from ..steps.agents import Agents
from ..steps.budget_guard import BudgetGuard
from ..steps.calls import AgentFailed, call_agent
from .base import StateMachine
from .validate import ValidateContext, ValidateMachine, VState

MAX_ROUNDS = 3
VALIDATE_CONCURRENCY = 3
RANK_ORDER = {
    ("GO", "STABLE"): 0,
    ("GO", "BORDERLINE"): 1,
    ("PIVOT", "STABLE"): 2,
    ("PIVOT", "BORDERLINE"): 2,
    ("NO-GO", "STABLE"): 3,
    ("NO-GO", "BORDERLINE"): 3,
    ("INSUFFICIENT_EVIDENCE", "STABLE"): 4,
    ("INSUFFICIENT_EVIDENCE", "BORDERLINE"): 4,
}


class DState(enum.Enum):
    REQUEST = "REQUEST"
    NICHES = "NICHES"
    IDEATE = "IDEATE"
    GAP = "GAP"
    SKEPTIC = "SKEPTIC"
    CRITIC = "CRITIC"
    DEBATE = "DEBATE"
    VALIDATE = "VALIDATE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RANK = "RANK"
    RESULT = "RESULT"
    DONE = "DONE"
    FAILED = "FAILED"


class DiscoverContext(BaseModel):
    run_id: str
    user_id: str
    niche: str | None = None
    count: int = 8
    profile: StudentProfile | None = None
    niches: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    round: int = 1
    ideas: list[dict[str, Any]] = []  # alive ideas, each {"id", ..., "objections": [...], "fatal_rounds": int}
    dropped: list[dict[str, Any]] = []  # {"idea", "reason", "round"}
    rejected: list[dict[str, Any]] = []  # ideas rejected at IDEATE (no / unknown gap evidence)
    results: list[dict[str, Any]] = []  # {"idea", "verdict", "reason"}
    pending_approval: dict[str, Any] | None = None
    validate_limit: int | None = None  # set when the user declines validating all survivors
    budget: dict[str, Any] = {}
    error: str | None = None


def rank_key(r: dict[str, Any]) -> tuple[Any, ...]:
    v = r["verdict"]
    return (RANK_ORDER.get((v["verdict"], v["stability"]), 5), -(v["score"] or 0.0), -v["confidence"])


def one_sentence_reason(v: Verdict) -> str:
    if v.verdict == "INSUFFICIENT_EVIDENCE":
        return "Not enough evidence: " + (v.missing[0] if v.missing else "missing data")
    if v.gate_details:
        k, d = next(iter(v.gate_details.items()))
        return f"{k} gate: {d}"
    best = max((s for s in v.scores if s.score is not None), key=lambda s: s.score or 0, default=None)
    weak = v.weakest_dimension or "n/a"
    sc = f"{v.score:.1f}" if v.score is not None else "n/a"
    return f"Score {sc}; strongest {best.dimension if best else 'n/a'}, weakest {weak}."


class _ChildAgents:
    """Validate runs inside Discover publish to the parent's channel and do not persist their own run row."""

    def __init__(self, inner: Agents, parent_run: str, idea_title: str) -> None:
        self._inner, self._parent, self._title = inner, parent_run, idea_title

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        await self._inner.publish(
            self._parent,
            {**event, "run_id": self._parent, "payload": {**event.get("payload", {}), "child": self._title}},
        )

    async def persist_run(self, run_id: str, state: str, context: dict[str, Any]) -> None:
        return None

    async def create_idea(self, user_id: str, text: str, source: str = "own") -> dict[str, Any]:
        return await self._inner.create_idea(user_id, text, "generated")


class DiscoverMachine(StateMachine[DState, DiscoverContext]):
    def __init__(
        self,
        ctx: DiscoverContext,
        agents: Agents,
        *,
        tracer: Tracer | None = None,
        guard: BudgetGuard | None = None,
        state: DState = DState.REQUEST,
    ) -> None:
        self.agents = agents
        self.guard = guard or BudgetGuard("discover", state=ctx.budget or None)
        tr = tracer or Tracer(ctx.run_id)
        transitions = {
            DState.REQUEST: self.request,
            DState.NICHES: self.niches,
            DState.IDEATE: self.ideate,
            DState.GAP: self.gap,
            DState.SKEPTIC: self.skeptic,
            DState.CRITIC: self.critic,
            DState.DEBATE: self.debate,
            DState.VALIDATE: self.validate,
            DState.RANK: self.rank,
            DState.RESULT: self.result,
        }
        super().__init__(state, ctx, transitions, emit=self._emit, persist=self._persist, tracer=tr)

    async def _emit(self, type_: str, payload: dict[str, Any]) -> None:
        await self.agents.publish(
            self.context.run_id,
            {"type": type_, "run_id": self.context.run_id, "ts": datetime.now(UTC).isoformat(), "payload": payload},
        )

    async def _persist(self, state: str, ctx: BaseModel) -> None:
        self.context.budget = self.guard.snapshot()
        await self.agents.persist_run(self.context.run_id, state, self.context.model_dump(mode="json"))

    async def _call(
        self, name: str, factory: Any, *, kind: str = "tool_call", cost: float = 0.0, input: Any = ""
    ) -> Any:
        r = await call_agent(name, factory, tracer=self.tracer, emit=self._emit, kind=kind, input=input, timeout_s=30)
        self.guard.spend(cost_usd=cost)
        await self._emit("spend", self.guard.snapshot())
        return r

    # ------------------------------------------------------------------ states
    async def request(self) -> DState:
        c = self.context
        if c.niche:
            rail = await self._call("input_rail", lambda: self.agents.input_rail(c.niche or ""))
            if rail["decision"] == "block":
                c.error = f"input blocked: {rail.get('reason')}"
                return DState.FAILED
            c.niche = rail["text"]
        c.profile = await self._call("profile", lambda: self.agents.get_profile(c.user_id))
        return DState.NICHES

    async def niches(self) -> DState:
        c = self.context
        assert c.profile is not None
        all_n = await self._call("analyst_niches", lambda: self.agents.niches(c.profile, c.niche))  # type: ignore[arg-type]
        wish = (c.niche or "").lower()
        interests = {i.lower() for i in c.profile.interests}

        def fit(n: dict[str, Any]) -> tuple[int, int, float]:
            text = (n["name"] + " " + " ".join(n.get("keywords", []))).lower()
            match = int(bool(wish) and any(w in text for w in wish.split())) * 2 + int(
                any(i in text for i in interests)
            )
            status = {"rising": 2, "flat": 1, "saturated": 0}.get(n.get("status", "flat"), 1)
            return (match, status, n.get("trend_slope", 0.0))

        chosen = [n for n in sorted(all_n, key=fit, reverse=True) if n.get("status") != "saturated"][:3]
        c.niches = chosen or all_n[:1]
        gaps: list[dict[str, Any]] = []
        for n in c.niches:
            gaps += await self._call("analyst_gaps", lambda n=n: self.agents.gaps(n["id"]))
        c.gaps = gaps
        return DState.IDEATE

    def _known_gap_ids(self) -> set[str]:
        return {i for g in self.context.gaps for i in g.get("evidence_ids", [])}

    async def ideate(self, revise: list[dict[str, Any]] | None = None) -> DState:
        c = self.context
        assert c.profile is not None
        payload = {
            "profile": c.profile.model_dump(),
            "niches": c.niches,
            "gaps": c.gaps,
            "count": c.count,
            "round": c.round,
            "revise": revise or [],
        }
        raw = await self._call("ideator", lambda: self.agents.ideate(payload), kind="llm_call", cost=0.003)
        known = self._known_gap_ids()
        fresh = []
        for i, idea in enumerate(raw):
            ids = idea.get("gap_evidence_ids") or []
            if not ids or not set(ids) <= known:
                c.rejected.append({"idea": idea, "reason": "no gap evidence" if not ids else "unknown gap evidence id"})
                self.tracer.record("ideator", "decision", idea.get("title", ""), "rejected: gap evidence")
                continue
            fresh.append(
                {
                    **idea,
                    "id": idea.get("id") or f"g{c.round}_{i}",
                    "objections": [],
                    "fatal_rounds": idea.get("fatal_rounds", 0),
                }
            )
        if revise is None:
            c.ideas = fresh
        else:
            revised_ids = {r["id"] for r in revise}
            c.ideas = [i for i in c.ideas if i["id"] not in revised_ids] + fresh
        return DState.GAP

    async def gap(self) -> DState:
        c = self.context
        out = []
        for idea in c.ideas:
            try:
                out.append(
                    await self._call(
                        "gap_analyst", lambda i=idea: self.agents.gap_analyse(i), kind="llm_call", cost=0.001
                    )
                )
            except AgentFailed:
                out.append(idea)
        c.ideas = out
        return DState.SKEPTIC

    async def skeptic(self) -> DState:
        c = self.context
        for idea in c.ideas:
            payload = {"idea": {"title": idea["title"], "text": idea.get("one_liner", "")}, "round": c.round}
            objs = await self._call("skeptic", lambda p=payload: self.agents.skeptic(p), kind="llm_call", cost=0.001)
            idea["objections"] = [o.model_dump() for o in objs]
        return DState.CRITIC

    async def critic(self) -> DState:
        for idea in self.context.ideas:
            objs = idea["objections"]
            if not objs:
                continue
            checks = await self._call(
                "critic_check",
                lambda o=objs: self.agents.check_claims(
                    [{"text": x["text"], "evidence_ids": x["evidence_ids"]} for x in o]
                ),
            )
            idea["objections"] = [
                {**o, "supported": ch["supported"]} for o, ch in zip(objs, checks, strict=False) if ch["supported"]
            ]  # only evidence-backed objections are kept
        return DState.DEBATE

    async def debate(self) -> DState:
        c = self.context
        fatal = [i for i in c.ideas if any(o.get("fatal") for o in i["objections"])]
        if not fatal:
            return DState.VALIDATE  # stop early: no (new) fatal objections
        for i in fatal:
            i["fatal_rounds"] = i.get("fatal_rounds", 0) + 1
        # an idea that already had a fatal objection last round and could not answer it is dropped
        to_drop = [i for i in fatal if i["fatal_rounds"] >= 2 or c.round >= MAX_ROUNDS]
        for i in to_drop:
            reason = next(o["text"] for o in i["objections"] if o.get("fatal"))
            c.dropped.append({"idea": i["title"], "reason": reason, "round": c.round})
            self.tracer.record("debate", "decision", i["title"], f"dropped: {reason}")
        drop_ids = {i["id"] for i in to_drop}
        c.ideas = [i for i in c.ideas if i["id"] not in drop_ids]
        to_revise = [i for i in fatal if i["id"] not in drop_ids]
        if not to_revise or c.round >= MAX_ROUNDS:
            return DState.VALIDATE
        c.round += 1
        await self.ideate(revise=to_revise)
        return DState.GAP

    async def validate(self) -> DState:
        c = self.context
        survivors = c.ideas if c.validate_limit is None else c.ideas[: c.validate_limit]
        done_titles = {r["idea"]["title"] for r in c.results}
        todo = [i for i in survivors if i["title"] not in done_titles]
        if c.validate_limit is None and c.pending_approval is None:
            est = self.guard.estimate("validate_one") * len(todo)
            need = self.guard.check("validate_survivors", est)
            if need is not None:
                c.pending_approval = {
                    "action": "validate_survivors",
                    "estimated_cost_usd": est,
                    "current_spend": need.current_spend,
                    "budget_usd": need.budget_usd,
                    "message": need.message,
                    "n_ideas": len(todo),
                }
                APPROVALS.labels("requested").inc()
                await self._emit("approval_required", c.pending_approval)
                return DState.WAITING_APPROVAL
        sem = asyncio.Semaphore(VALIDATE_CONCURRENCY)

        async def one(idx: int, idea: dict[str, Any]) -> dict[str, Any] | None:
            async with sem:
                text = (
                    f"{idea['title']}: {idea.get('one_liner', '')} Problem: {idea.get('problem', '')}. "
                    f"Customer: {idea.get('customer', '')}."
                )
                ctx = ValidateContext(run_id=f"{c.run_id}-v{idx}", user_id=c.user_id, idea_text=text, skip_clarify=True)
                m = ValidateMachine(
                    ctx,
                    _ChildAgents(self.agents, c.run_id, idea["title"]),  # type: ignore[arg-type]
                    tracer=self.tracer,
                    guard=self.guard,
                )
                state = await m.run()
                if state != VState.DONE or ctx.verdict is None:
                    return None
                return {
                    "idea": {k: idea[k] for k in idea if k != "objections"},
                    "verdict": ctx.verdict.model_dump(mode="json"),
                    "reason": one_sentence_reason(ctx.verdict),
                }

        res = await asyncio.gather(*(one(i, idea) for i, idea in enumerate(todo)))
        c.results += [r for r in res if r]
        return DState.RANK

    async def approve(self, approve: bool) -> None:
        c = self.context
        c.pending_approval = None
        if not approve:
            # validate only what the remaining budget covers (at least one idea)
            left = max(0.0, self.guard.state.budget.max_cost_usd - self.guard.state.cost_usd)
            c.validate_limit = max(1, int(left // max(self.guard.estimate("validate_one"), 1e-9)))
        else:
            # the user approved going over budget by the stated estimate
            est = self.guard.estimate("validate_one") * len(c.ideas)
            self.guard.state.budget.max_cost_usd = max(
                self.guard.state.budget.max_cost_usd, self.guard.state.cost_usd + est
            )
            c.validate_limit = len(c.ideas)
        self.resume_to(DState.VALIDATE)

    async def rank(self) -> DState:
        self.context.results.sort(key=rank_key)
        return DState.RESULT

    async def result(self) -> DState:
        c = self.context
        await self.tracer.flush()
        ranked = [
            {
                "rank": n + 1,
                "title": r["idea"]["title"],
                "verdict": r["verdict"]["verdict"],
                "stability": r["verdict"]["stability"],
                "score": r["verdict"]["score"],
                "reason": r["reason"],
                "idea_id": r["verdict"]["idea_id"],
                "version": r["verdict"]["version"],
            }
            for n, r in enumerate(c.results)
        ]
        await self._emit("result", {"ranked": ranked, "dropped": c.dropped, "rejected": len(c.rejected)})
        return DState.DONE

"""Validate workflow (Section 10.1) as an explicit state machine."""

from __future__ import annotations

import asyncio
import enum
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from ivcommon.cachekeys import cache_key
from ivcommon.metrics import APPROVALS, VERDICT_COST
from ivcommon.schemas.core import DimensionScore, EvidenceItem, StudentProfile, Verdict
from ivcommon.tracing import Tracer

from ..steps.agents import RUBRIC_SET_VERSION, RUBRIC_VERSIONS, SCORER_DIMS, Agents
from ..steps.budget_guard import BudgetGuard
from ..steps.calls import AgentFailed, call_agent
from ..steps.clarify import questions_that_matter
from .base import StateMachine

ENGINE_VERSION = "m11@v1"
WEIGHTS_VERSION = "w1"
KB_SNAPSHOT_ID = "kb-live"


class VState(enum.Enum):
    INTAKE = "INTAKE"
    CLARIFY_CHECK = "CLARIFY_CHECK"
    WAITING_ANSWER = "WAITING_ANSWER"
    EVIDENCE = "EVIDENCE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SCORING = "SCORING"
    VERDICT = "VERDICT"
    CHALLENGE = "CHALLENGE"
    STABILITY = "STABILITY"
    CARD = "CARD"
    DONE = "DONE"
    FAILED = "FAILED"


class ValidateContext(BaseModel):
    run_id: str
    user_id: str
    kind: str = "validate"  # validate | whatif
    idea_text: str = ""
    idea_id: str | None = None
    version: int = 1
    change_applied: str | None = None
    profile: StudentProfile | None = None
    questions: list[dict[str, str]] = []
    answers: dict[str, str] = {}
    assumptions: list[str] = []
    evidence: list[EvidenceItem] = []
    n_sources: int = 0
    n_platforms: int = 0
    deep_search_done: bool = False
    deep_search_declined: bool = False
    pending_approval: dict[str, Any] | None = None
    scores: list[DimensionScore] = []
    score_hashes: dict[str, str] = {}
    prev_scores: list[DimensionScore] = []
    prev_score_hashes: dict[str, str] = {}
    rerun_scorers: list[str] = []
    scorer_texts: dict[str, str] = {}  # what-if: unaffected scorers keep the previous version's text
    verdict: Verdict | None = None
    preliminary: Verdict | None = None
    objections: list[dict[str, Any]] = []
    cache_hit: bool = False
    error: str | None = None
    budget: dict[str, Any] = {}
    skip_clarify: bool = False
    timeouts: dict[str, float] = {"scorer": 60.0, "search": 15.0, "default": 20.0}


def count_sources(evidence: list[EvidenceItem]) -> tuple[int, int]:
    """Independent sources = distinct cards (one card = one product/discussion); platforms = distinct sources."""
    return len({e.card_id for e in evidence}), len({e.source for e in evidence})


def scorer_input_hash(scorer: str, idea_text: str, evidence_ids: list[str], model: str = "scorer") -> str:
    rubrics = [RUBRIC_VERSIONS[d] for d in SCORER_DIMS[scorer]]
    raw = json.dumps([scorer, idea_text.strip().lower(), sorted(evidence_ids), rubrics, model], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def abstain(dim: str, reason: str) -> DimensionScore:
    return DimensionScore(
        dimension=dim,
        score=None,
        confidence=0.0,
        evidence_ids=[],
        reason=reason,  # type: ignore[arg-type]
        rubric_version=RUBRIC_VERSIONS[dim],
        model="none",
        abstained=True,
    )


class ValidateMachine(StateMachine[VState, ValidateContext]):
    def __init__(
        self,
        ctx: ValidateContext,
        agents: Agents,
        *,
        tracer: Tracer | None = None,
        guard: BudgetGuard | None = None,
        state: VState = VState.INTAKE,
    ) -> None:
        self.agents = agents
        self.guard = guard or BudgetGuard(
            ctx.kind if ctx.kind in ("validate", "whatif") else "validate", state=ctx.budget or None
        )
        tracer = tracer or Tracer(ctx.run_id)
        transitions = {
            VState.INTAKE: self.intake,
            VState.CLARIFY_CHECK: self.clarify_check,
            VState.EVIDENCE: self.evidence,
            VState.SCORING: self.scoring,
            VState.VERDICT: self.verdict_step,
            VState.CHALLENGE: self.challenge,
            VState.STABILITY: self.stability,
            VState.CARD: self.card,
        }
        super().__init__(state, ctx, transitions, emit=self._emit, persist=self._persist, tracer=tracer)

    # ----------------------------------------------------------------- plumbing
    async def _emit(self, type_: str, payload: dict[str, Any]) -> None:
        ev = {"type": type_, "run_id": self.context.run_id, "ts": datetime.now(UTC).isoformat(), "payload": payload}
        await self.agents.publish(self.context.run_id, ev)

    async def _persist(self, state: str, ctx: BaseModel) -> None:
        self.context.budget = self.guard.snapshot()
        await self.agents.persist_run(self.context.run_id, state, self.context.model_dump(mode="json"))

    async def _call(
        self,
        name: str,
        factory: Any,
        *,
        timeout: str = "default",
        input: Any = "",
        retries: int = 2,
        kind: str = "tool_call",
        cost: float = 0.0,
    ) -> Any:
        r = await call_agent(
            name,
            factory,
            tracer=self.tracer,
            emit=self._emit,
            input=input,
            retries=retries,
            timeout_s=self.context.timeouts.get(timeout, 20.0),
            kind=kind,
        )
        self.guard.spend(cost_usd=cost)
        await self._emit("spend", self.guard.snapshot())
        return r

    def verdict_cache_key(self) -> str:
        assert self.context.profile is not None
        return cache_key(
            "verdict",
            idea_text=self.context.idea_text,
            profile_version=self.context.profile.profile_version,
            profile_weights_version=WEIGHTS_VERSION,
            rubric_set_version=RUBRIC_SET_VERSION,
            engine_version=ENGINE_VERSION,
            kb_snapshot_id=KB_SNAPSHOT_ID,
        )

    # ----------------------------------------------------------------- states
    async def intake(self) -> VState:
        c = self.context
        rail = await self._call("input_rail", lambda: self.agents.input_rail(c.idea_text), input=c.idea_text[:200])
        if rail["decision"] == "block":
            c.error = f"input blocked: {rail.get('reason', '')}"
            await self._emit("error", {"reason": c.error})
            return VState.FAILED
        if rail["decision"] == "sanitized":
            c.idea_text = rail["text"]
        c.profile = await self._call("profile", lambda: self.agents.get_profile(c.user_id))
        if c.kind == "whatif":
            # version N+1 already created; evidence carried over -> straight to SCORING (re-run only what changed)
            return VState.SCORING
        if c.idea_id is None:
            idea = await self._call("create_idea", lambda: self.agents.create_idea(c.user_id, c.idea_text))
            c.idea_id, c.version = idea["id"], idea.get("version", 1)
        cached = await self._call("verdict_cache", lambda: self.agents.cache_get(self.verdict_cache_key()))
        if cached:
            c.cache_hit = True
            v = Verdict.model_validate({**cached, "idea_id": c.idea_id, "version": c.version, "run_id": c.run_id})
            c.verdict = v.model_copy(update={"cache_hit": True})
            await self._emit("result", {"verdict": c.verdict.model_dump(mode="json"), "cache_hit": True})
            return VState.DONE
        return VState.EVIDENCE if c.skip_clarify else VState.CLARIFY_CHECK

    async def clarify_check(self) -> VState:
        c = self.context
        assert c.profile is not None
        fields = await self._call(
            "extract_fields",
            lambda: self.agents.extract_fields(c.idea_text),
            kind="llm_call",
            input=c.idea_text[:200],
            cost=0.0005,
        )
        fields.update({k.removeprefix("q_"): v for k, v in c.answers.items()})
        qs = await questions_that_matter(fields, c.profile, self.agents.whatif)
        if not qs:
            return VState.EVIDENCE
        c.questions = qs
        for q in qs:
            await self._emit("question", q)
        return VState.WAITING_ANSWER

    def answer(self, question_id: str, answer: str) -> bool:
        """Record an answer; returns True when all questions are answered (the machine can resume)."""
        c = self.context
        c.answers[question_id] = answer
        c.idea_text = f"{c.idea_text}\n{question_id.removeprefix('q_')}: {answer}"
        return all(q["id"] in c.answers for q in c.questions)

    def proceed_with_assumptions(self) -> None:
        c = self.context
        for q in c.questions:
            if q["id"] not in c.answers:
                c.assumptions.append(f"{q['field']}: not answered; assumed a typical value")
        self.resume_to(VState.EVIDENCE)

    async def evidence(self) -> VState:
        c = self.context
        queries = [
            c.idea_text[:300],
            f"problem complaints {c.idea_text[:150]}",
            f"competitors {c.idea_text[:150]}",
            f"customers who need {c.idea_text[:150]}",
        ]
        results = await asyncio.gather(
            *(
                self._call("kb_search", lambda q=q: self.agents.search(q, 10), input=q, timeout="search")
                for q in queries
            ),
            return_exceptions=True,
        )
        seen: dict[str, EvidenceItem] = {e.evidence_id: e for e in c.evidence}
        for r in results:
            if isinstance(r, BaseException):
                continue
            for e in r:
                seen.setdefault(e.evidence_id, e)
        c.evidence = list(seen.values())
        c.n_sources, c.n_platforms = count_sources(c.evidence)
        thin = c.n_sources < 3 or c.n_platforms < 2
        if thin and not c.deep_search_done and not c.deep_search_declined:
            need = self.guard.check("deep_search")
            if need is not None:
                c.pending_approval = {
                    "action": "deep_search",
                    "estimated_cost_usd": need.estimated_cost_usd,
                    "current_spend": need.current_spend,
                    "budget_usd": need.budget_usd,
                    "message": need.message,
                }
                APPROVALS.labels("requested").inc()
                await self._emit("approval_required", c.pending_approval)
                return VState.WAITING_APPROVAL
            await self.deep_search()
            return VState.EVIDENCE
        return VState.SCORING

    async def deep_search(self) -> None:
        c = self.context
        try:
            await self._call(
                "scout_on_demand",
                lambda: self.agents.scout(c.idea_text[:200], c.run_id),
                cost=self.guard.estimate("deep_search"),
                timeout="default",
                retries=1,
            )
        except AgentFailed:
            pass  # degrade: continue with what we have
        c.deep_search_done = True

    async def approve(self, approve: bool) -> None:
        c = self.context
        c.pending_approval = None
        if approve:
            await self.deep_search()
        else:
            c.deep_search_declined = True
        self.resume_to(VState.EVIDENCE if approve else VState.SCORING)

    async def scoring(self) -> VState:
        """4 scorers in parallel; re-run only what changed (scorer input hash)."""
        c = self.context
        ev_ids = [e.evidence_id for e in c.evidence]
        prev_by_dim = {s.dimension: s for s in c.prev_scores}

        async def one(scorer: str) -> list[DimensionScore]:
            text = c.scorer_texts.get(scorer, c.idea_text)
            h = scorer_input_hash(scorer, text, ev_ids)
            c.score_hashes[scorer] = h
            if c.prev_score_hashes.get(scorer) == h and all(d in prev_by_dim for d in SCORER_DIMS[scorer]):
                reused = [prev_by_dim[d].model_copy(update={"cache_hit": True}) for d in SCORER_DIMS[scorer]]
                self.tracer.record(f"{scorer}_scorer", "tool_call", h, "reused previous score", cache_hit=True)
                await self._emit("tool_call", {"agent": f"{scorer}_scorer", "cache_hit": True, "latency_ms": 0})
                return reused
            c.rerun_scorers.append(scorer)
            payload = {
                "idea": {"text": text},
                "evidence": [e.model_dump(mode="json") for e in c.evidence],
                "profile": c.profile.model_dump() if c.profile else None,
            }
            try:
                return await self._call(
                    f"{scorer}_scorer",
                    lambda: self.agents.score(scorer, payload, c.run_id),  # type: ignore[no-any-return]
                    timeout="scorer",
                    input=h,
                    kind="llm_call",
                    cost=self.guard.estimate("scorer_call"),
                )
            except AgentFailed as e:
                return [abstain(d, f"{scorer} scorer failed: {e.last!r}") for d in SCORER_DIMS[scorer]]

        groups = await asyncio.gather(*(one(s) for s in SCORER_DIMS))
        c.scores = [s for g in groups for s in g]
        return VState.VERDICT

    def _verdict_payload(self, adjustments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        c = self.context
        assert c.profile is not None
        return {
            "idea_id": c.idea_id,
            "version": c.version,
            "run_id": c.run_id,
            "scores": [s.model_dump(mode="json") for s in c.scores],
            "profile": c.profile.model_dump(),
            "n_sources": c.n_sources,
            "n_platforms": c.n_platforms,
            "rubric_set_version": RUBRIC_SET_VERSION,
            "challenge_adjustments": adjustments or [],
        }

    async def verdict_step(self) -> VState:
        c = self.context
        c.preliminary = await self._call(
            "verdict_engine", lambda: self.agents.verdict(self._verdict_payload()), kind="decision"
        )
        c.verdict = c.preliminary
        # nothing to challenge if the engine could not score
        return VState.CHALLENGE if c.preliminary.score is not None else VState.STABILITY

    async def challenge(self) -> VState:
        c = self.context
        assert c.preliminary is not None
        payload = {
            "idea": {"text": c.idea_text},
            "scores": [s.model_dump(mode="json") for s in c.scores],
            "evidence": [e.model_dump(mode="json") for e in c.evidence],
        }
        try:
            objections = await self._call("skeptic", lambda: self.agents.skeptic(payload), kind="llm_call", cost=0.001)
        except AgentFailed:
            objections = []
        if not objections:
            return VState.STABILITY
        checks = await self._call(
            "critic_check",
            lambda: self.agents.check_claims([{"text": o.text, "evidence_ids": o.evidence_ids} for o in objections]),
        )
        counts: dict[str, int] = {}
        c.objections = []
        for o, chk in zip(objections, checks, strict=False):
            c.objections.append({**o.model_dump(), "supported": chk["supported"], "reason": chk.get("reason", "")})
            if chk["supported"]:
                counts[o.dimension] = counts.get(o.dimension, 0) + 1
        if counts:
            adj = [{"dimension": d, "accepted_objections": k} for d, k in counts.items()]
            c.verdict = await self._call(
                "verdict_engine", lambda: self.agents.verdict(self._verdict_payload(adj)), kind="decision"
            )
        return VState.STABILITY

    async def stability(self) -> VState:
        """Sensitivity + what-if come from M11; M8 words the options concretely."""
        c = self.context
        assert c.verdict is not None
        worded = []
        for opt in c.verdict.what_would_make_go:
            try:
                text = await self._call(
                    "suggest_change",
                    lambda o=opt: self.agents.suggest_change(
                        {"idea": c.idea_text, "dimension": o.dimension, "delta": o.delta, "change": o.change}
                    ),
                    kind="llm_call",
                    retries=1,
                    cost=0.0005,
                )
            except AgentFailed:
                text = opt.change
            worded.append(opt.model_copy(update={"change": text}))
        c.verdict = c.verdict.model_copy(update={"what_would_make_go": worded})
        return VState.CARD

    async def card(self) -> VState:
        c = self.context
        assert c.verdict is not None
        if c.assumptions:
            c.verdict = c.verdict.model_copy(update={"missing": [*c.verdict.missing, *c.assumptions]})
        await self._call("save_verdict", lambda: self.agents.save_verdict(c.verdict))  # type: ignore[arg-type]
        await self._call(
            "verdict_cache_put",
            lambda: self.agents.cache_put(self.verdict_cache_key(), c.verdict.model_dump(mode="json")),
        )  # type: ignore[union-attr]
        VERDICT_COST.observe(self.guard.state.cost_usd)
        await self.tracer.flush()
        await self._emit(
            "result", {"verdict": c.verdict.model_dump(mode="json"), "cache_hit": False, "objections": c.objections}
        )
        return VState.DONE

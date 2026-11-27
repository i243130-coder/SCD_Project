import pytest

from ivcommon.schemas.core import Objection, StudentProfile
from ivcommon.tracing import Tracer
from src.machines.validate import ValidateContext, ValidateMachine, VState
from src.steps.budget_guard import BudgetGuard
from tests.fakes import FakeAgents

HAPPY = ["INTAKE", "CLARIFY_CHECK", "EVIDENCE", "SCORING", "VERDICT", "CHALLENGE", "STABILITY", "CARD", "DONE"]


def machine(agents, **ctx):
    c = ValidateContext(run_id="run_t", user_id="u1", idea_text=ctx.pop("idea_text", "Event tool for clubs"), **ctx)
    c.timeouts = {"scorer": 0.3, "search": 1.0, "default": 1.0}
    return ValidateMachine(c, agents, tracer=Tracer("run_t", send=False, echo=False))


async def test_transition_table_happy_path():
    a = FakeAgents()
    m = machine(a)
    assert await m.run() == VState.DONE
    assert m.history == HAPPY
    assert a.persisted == HAPPY[1:]  # persisted after every transition
    assert m.context.verdict is not None and m.context.verdict.verdict in ("GO", "PIVOT")
    assert sorted(a.score_calls) == ["competition", "demand", "feasibility", "risk"]
    types = {e["type"] for e in a.events}
    assert {"state", "agent_start", "tool_call", "spend", "result"} <= types
    assert any(r.kind == "decision" for r in m.tracer.records)


async def test_input_blocked_fails():
    m = machine(FakeAgents(rail="block"))
    assert await m.run() == VState.FAILED
    assert "blocked" in (m.context.error or "")


async def test_cache_hit_short_circuits():
    a = FakeAgents()
    m0 = machine(a)
    await m0.run()
    cached = m0.context.verdict.model_dump(mode="json")
    a2 = FakeAgents(cached=cached)
    m = machine(a2)
    assert await m.run() == VState.DONE
    assert m.history == ["INTAKE", "DONE"]
    assert m.context.verdict.cache_hit is True
    assert a2.score_calls == []


async def test_clarify_asks_only_questions_that_change_result():
    # 240 available hours: small scope (80h) passes, large scope (400h) fails -> the scope question matters
    a = FakeAgents(fields={"customer": "club organisers", "platform": "web", "core_features": "rsvp"})
    m = machine(a)
    assert await m.run() == VState.WAITING_ANSWER
    assert [q["field"] for q in m.context.questions] == ["scope"]
    assert any(e["type"] == "question" for e in a.events)
    assert m.answer("q_scope", "one feature, web only")
    m.resume_to(VState.EVIDENCE)
    assert await m.run() == VState.DONE


async def test_no_question_when_answer_cannot_change_verdict():
    rich = StudentProfile(
        user_id="u1",
        skills=["python"],
        hours_per_week=40,
        weeks_available=20,
        team_size=3,
        compute="laptop",
        goal="portfolio",
    )  # 2400h: even the big scope fits
    a = FakeAgents(profile=rich, fields={"customer": "x", "platform": "web", "core_features": "y"})
    m = machine(a)
    assert await m.run() == VState.DONE
    assert m.context.questions == []


async def test_budget_stop_asks_user_and_decline_continues():
    a = FakeAgents(n_evidence=2)  # thin: 2 sources
    m = machine(a, skip_clarify=True)
    m.guard = BudgetGuard("validate", state={"cost_usd": 0.04})  # 0.04 + 0.03 > 0.05
    assert await m.run() == VState.WAITING_APPROVAL
    ev = next(e for e in a.events if e["type"] == "approval_required")
    assert ev["payload"]["estimated_cost_usd"] == pytest.approx(0.03)
    await m.approve(False)
    assert await m.run() == VState.DONE
    assert m.context.verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert m.context.verdict.missing


async def test_deep_search_within_budget_runs_without_asking():
    a = FakeAgents(n_evidence=2, scout_adds=4)
    m = machine(a, skip_clarify=True)
    assert await m.run() == VState.DONE
    assert m.context.deep_search_done and m.context.n_sources >= 3
    assert not any(e["type"] == "approval_required" for e in a.events)


async def test_timeout_retry_then_success():
    a = FakeAgents(scorer_fail_times={"risk": 1})
    m = machine(a, skip_clarify=True)
    assert await m.run() == VState.DONE
    assert a.score_calls.count("risk") == 2
    rec = next(r for r in m.tracer.records if r.agent == "risk_scorer" and r.error is None)
    assert rec.retries == 1


async def test_timeout_exhausted_abstains():
    a = FakeAgents(scorer_fail_times={"risk": 5})
    m = machine(a, skip_clarify=True)
    assert await m.run() == VState.DONE
    risk = next(s for s in m.context.scores if s.dimension == "risk")
    assert risk.abstained and risk.score is None
    assert m.context.verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert "no evidence for risk" in m.context.verdict.missing


async def test_scorers_run_in_parallel():
    import time

    a = FakeAgents(scorer_delay={"demand": 0.15, "competition": 0.15, "feasibility": 0.15, "risk": 0.15})
    m = machine(a, skip_clarify=True)
    t0 = time.perf_counter()
    await m.run()
    assert time.perf_counter() - t0 < 0.45  # sequential would be >= 0.6


async def test_challenge_supported_objection_lowers_score():
    obj = Objection(dimension="competition", text="Eventbrite already does this", evidence_ids=["card_0001#c0"])
    a = FakeAgents(objections=[obj], supported=True)
    m = machine(a, skip_clarify=True)
    await m.run()
    comp = next(s for s in m.context.verdict.scores if s.dimension == "competition")
    assert comp.score == pytest.approx(3.0)
    assert m.context.objections[0]["supported"]


async def test_unsupported_objection_ignored():
    obj = Objection(dimension="competition", text="made up", evidence_ids=["card_0001#c0"])
    m = machine(FakeAgents(objections=[obj], supported=False), skip_clarify=True)
    await m.run()
    comp = next(s for s in m.context.verdict.scores if s.dimension == "competition")
    assert comp.score == pytest.approx(3.5)


async def test_whatif_reruns_only_changed_scorer():
    a = FakeAgents()
    m1 = machine(a, skip_clarify=True)
    await m1.run()
    c1 = m1.context
    a.score_calls.clear()
    texts = {s: c1.idea_text for s in ("demand", "competition", "risk")}  # feasibility affected
    m2 = machine(
        a,
        kind="whatif",
        idea_id=c1.idea_id,
        version=2,
        idea_text=c1.idea_text + " (web only, 1 feature)",
        evidence=c1.evidence,
        n_sources=c1.n_sources,
        n_platforms=c1.n_platforms,
        prev_scores=c1.scores,
        prev_score_hashes=c1.score_hashes,
        scorer_texts=texts,
    )
    assert await m2.run() == VState.DONE
    assert a.score_calls == ["feasibility"]
    assert m2.context.rerun_scorers == ["feasibility"]
    reused = [s for s in m2.context.scores if s.cache_hit]
    assert {s.dimension for s in reused} == {"demand_pain", "competition", "differentiation", "risk"}
    assert m2.context.verdict.version == 2


async def test_profile_changes_verdict():
    """Same large idea: solo 20h -> NO-GO (feasibility gate); team of 2 with 200h -> passes the gate."""
    solo = StudentProfile(
        user_id="u1",
        skills=["python"],
        hours_per_week=2,
        weeks_available=10,
        team_size=1,
        compute="laptop",
        goal="portfolio",
    )
    team = StudentProfile(
        user_id="u1",
        skills=["python"],
        hours_per_week=10,
        weeks_available=10,
        team_size=2,
        compute="laptop",
        goal="portfolio",
    )
    v = {}
    for name, p in (("solo", solo), ("team", team)):
        m = machine(FakeAgents(profile=p, effort_hours=180), skip_clarify=True)
        await m.run()
        v[name] = m.context.verdict
    assert v["solo"].verdict == "NO-GO" and v["solo"].gates["feasibility"] == "fail"
    assert v["team"].gates["feasibility"] == "pass" and v["team"].verdict != "NO-GO"

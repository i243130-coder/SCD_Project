"""§15 behaviour tests with recorded responses (no live model, no network)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from svcload import load_service
from fastapi.testclient import TestClient

from ivcommon.metrics import FALLBACKS, INJECTIONS
from ivcommon.schemas.core import DimensionScore, EvidenceItem
from ivcommon.tracing import Tracer

FIX = Path(__file__).parent / "fixtures"
REC = json.loads((FIX / "scorer_responses.json").read_text())
orch = load_service("orchestrator")
scorer = load_service("scorer")
tools = load_service("tools")
validators = load_service("validators")
Validate = orch("machines.validate")
Discover = orch("machines.discover")
Guard = orch("steps.budget_guard")

import importlib.util, sys  # noqa: E401,E402

spec = importlib.util.spec_from_file_location(
    "orch_fakes", Path(__file__).resolve().parents[2] / "services/orchestrator/tests/fakes.py"
)
fakes = importlib.util.module_from_spec(spec)
sys.modules["orch_fakes"] = fakes
spec.loader.exec_module(fakes)


def vm(agents, **kw):
    c = Validate.ValidateContext(run_id="run_b", user_id="u", idea_text="RSVP tool for clubs", skip_clarify=True, **kw)
    c.timeouts = {"scorer": 0.3, "search": 0.2, "default": 0.5}
    return Validate.ValidateMachine(c, agents, tracer=Tracer("run_b", send=False, echo=False))


class Recorded:
    def __init__(self, name, outputs):
        self.name, self.outputs = name, list(outputs)

    async def generate(self, req, rubric_text):
        return self.outputs.pop(0), {}


# 1. invalid JSON from a scorer -> retry -> fallback -> verdict still produced; fallback logged
async def test_invalid_json_scorer_falls_back_and_verdict_produced():
    app = scorer("main").app
    before = FALLBACKS.labels("risk")._value.get()

    class Agents(fakes.FakeAgents):
        async def score(self, name, payload, run_id):
            if name != "risk":
                return await super().score(name, payload, run_id)
            app.state.primary = Recorded("scorer-lora@v1", REC["invalid_then_invalid"])
            app.state.fallback = Recorded("hosted:recorded", [REC["hosted_valid"]])
            req = {"rubric": "risk@v1", "dimension": "risk", "idea": payload["idea"], "evidence": payload["evidence"]}
            r = await asyncio.to_thread(lambda: TestClient(app).post("/score", json=req).json())
            return [DimensionScore.model_validate(r)]

    m = vm(Agents())
    assert (await m.run()).name == "DONE"
    risk = next(s for s in m.context.verdict.scores if s.dimension == "risk")
    assert risk.model == "hosted:recorded" and risk.extra["fallback"] is True
    assert m.context.verdict.verdict in ("GO", "PIVOT", "NO-GO")
    assert FALLBACKS.labels("risk")._value.get() == before + 1


# 2. tool timeout -> retry -> degrade gracefully, no crash
async def test_tool_timeout_degrades():
    class Slow(fakes.FakeAgents):
        async def search(self, *a, **k):
            await asyncio.sleep(5)

    m = vm(Slow())
    assert (await m.run()).name == "DONE"
    assert m.context.verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert any(r.agent == "kb_search" and r.error for r in m.tracer.records)


# 3. empty source -> the run completes with INSUFFICIENT_EVIDENCE
async def test_empty_source_completes():
    m = vm(fakes.FakeAgents(n_evidence=0))
    assert (await m.run()).name == "DONE"
    v = m.context.verdict
    assert v.verdict == "INSUFFICIENT_EVIDENCE" and v.missing


# 4. poisoned page -> sanitised + flagged; score unchanged vs the clean fixture; counter incremented
async def test_poisoned_page_does_not_change_score():
    pe = json.loads((FIX / "poisoned_evidence.json").read_text())
    san = tools("sanitiser").sanitise
    before = INJECTIONS.labels("tools")._value.get()
    clean, poisoned = san(pe["clean"]), san(pe["poisoned"], is_html=True)
    assert poisoned.flagged and not clean.flagged
    INJECTIONS.labels("tools").inc(len(poisoned.injection_flags))
    assert INJECTIONS.labels("tools")._value.get() > before

    rule = scorer("backends").RuleBackend()

    async def score_fn(req):
        raw, _ = await rule.generate(req, "")
        return scorer("main").parse(raw, req, "rule")

    def ev(q):
        return [
            EvidenceItem(
                evidence_id=f"card_{i}#c0",
                card_id=f"card_{i}",
                quote=q,
                source=s,
                url="https://x",
                retrieved_at=datetime.now(UTC),
            )
            for i, s in enumerate(["hackernews", "github", "producthunt"])
        ]

    demand = validators("scorers.demand").run
    s_clean = (await demand(score_fn, "RSVP tool", ev(clean.text), None, {}))[0]
    s_pois = (await demand(score_fn, "RSVP tool", ev(poisoned.text), None, {}))[0]
    assert s_clean.score == s_pois.score and s_pois.score != 5


# 5. budget exceeded -> approval_required; decline -> finishes without the deep search
async def test_budget_exceeded_decline():
    a = fakes.FakeAgents(n_evidence=2, scout_adds=5)
    m = vm(a)
    m.guard = Guard.BudgetGuard("validate", state={"cost_usd": 0.049})
    assert (await m.run()).name == "WAITING_APPROVAL"
    assert any(e["type"] == "approval_required" for e in a.events)
    await m.approve(False)
    assert (await m.run()).name == "DONE"
    assert not m.context.deep_search_done and a.n_evidence == 2


# 6. the debate stops at 3 rounds
async def test_debate_stops_at_three_rounds():
    from ivcommon.schemas.core import Objection

    class Always(fakes.FakeAgents):
        async def ideate(self, p):
            base = await super().ideate({"count": 2})
            return [{**i, "id": f"r{p['round']}_{n}", "fatal_rounds": 0} for n, i in enumerate(base)]

        async def skeptic(self, p):
            return [Objection(dimension="feasibility", text="too big", evidence_ids=["card_0001#c0"], fatal=True)]

    m = Discover.DiscoverMachine(
        Discover.DiscoverContext(run_id="run_d", user_id="u", count=2),
        Always(),
        tracer=Tracer("run_d", send=False, echo=False),
    )
    assert (await m.run()).name == "DONE"
    assert m.context.round == 3 and m.history.count("SKEPTIC") == 3

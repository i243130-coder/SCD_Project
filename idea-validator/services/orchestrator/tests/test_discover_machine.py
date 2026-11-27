from ivcommon.schemas.core import Objection
from ivcommon.tracing import Tracer
from src.machines.discover import DiscoverContext, DiscoverMachine, DState, rank_key
from src.steps.budget_guard import BudgetGuard
from tests.fakes import FakeAgents


class DebateAgents(FakeAgents):
    """Skeptic raises a fatal objection against titles in `fatal_for` every round (they can't answer it)."""

    def __init__(self, fatal_for=(), fatal_rounds_only=None, supported=True, **kw):
        super().__init__(supported=supported, **kw)
        self.fatal_for = set(fatal_for)
        self.fatal_rounds_only = fatal_rounds_only
        self.ideate_calls = []
        self.skeptic_rounds = []

    async def ideate(self, payload):
        self.ideate_calls.append(payload)
        if payload["revise"]:
            return [
                {**{k: v for k, v in r.items() if k not in ("objections",)}, "title": r["title"]}
                for r in payload["revise"]
            ]
        return [
            {
                "title": f"Idea {i}",
                "one_liner": "x",
                "problem": "p",
                "customer": "c",
                "niche_id": "n1",
                "gap_evidence_ids": ["card_0001#c0"],
            }
            for i in range(3)
        ] + [
            {"title": "No evidence idea", "one_liner": "x", "problem": "p", "customer": "c", "gap_evidence_ids": []},
            {
                "title": "Fake evidence idea",
                "one_liner": "x",
                "problem": "p",
                "customer": "c",
                "gap_evidence_ids": ["card_9999#c0"],
            },
        ]

    async def skeptic(self, payload):
        self.skeptic_rounds.append(payload["round"])
        t = payload["idea"]["title"]
        if t in self.fatal_for and (self.fatal_rounds_only is None or payload["round"] in self.fatal_rounds_only):
            return [
                Objection(
                    dimension="competition",
                    text=f"{t} duplicates Eventbrite",
                    evidence_ids=["card_0001#c0"],
                    fatal=True,
                )
            ]
        return []


def machine(agents, **kw):
    return DiscoverMachine(
        DiscoverContext(run_id="run_d", user_id="u1", **kw), agents, tracer=Tracer("run_d", send=False, echo=False)
    )


async def test_happy_path_ranked_list():
    a = DebateAgents()
    m = machine(a)
    assert await m.run() == DState.DONE
    assert m.history[:7] == ["REQUEST", "NICHES", "IDEATE", "GAP", "SKEPTIC", "CRITIC", "DEBATE"]
    res = next(e for e in a.events if e["type"] == "result" and "ranked" in e["payload"])["payload"]
    assert len(res["ranked"]) == 3
    assert all(r["reason"] and r["verdict"] for r in res["ranked"])
    # saturated niches are avoided
    assert all(n["status"] != "saturated" for n in m.context.niches)


async def test_idea_without_gap_evidence_rejected():
    m = machine(DebateAgents())
    await m.run()
    reasons = {r["idea"]["title"]: r["reason"] for r in m.context.rejected}
    assert reasons["No evidence idea"] == "no gap evidence"
    assert reasons["Fake evidence idea"] == "unknown gap evidence id"


async def test_defeated_idea_dropped():
    a = DebateAgents(fatal_for={"Idea 0"})
    m = machine(a)
    await m.run()
    assert [d["idea"] for d in m.context.dropped] == ["Idea 0"]
    assert "Idea 0" not in {i["title"] for i in m.context.ideas}


async def test_debate_stops_at_three_rounds():
    a = DebateAgents(fatal_for={"Idea 0"})
    # make the revise call produce a new id each time so it is never "repeat fatal" -> forces rounds to the cap
    orig = a.ideate

    async def ideate(payload):
        out = await orig(payload)
        if payload["revise"]:
            for o in out:
                o["id"] = f"rev{payload['round']}"
                o["fatal_rounds"] = 0
        return out

    a.ideate = ideate
    m = machine(a)
    assert await m.run() == DState.DONE
    assert m.context.round == 3
    assert max(a.skeptic_rounds) == 3
    assert m.history.count("SKEPTIC") == 3


async def test_revised_idea_survives_when_objection_answered():
    a = DebateAgents(fatal_for={"Idea 0"}, fatal_rounds_only={1})
    m = machine(a)
    await m.run()
    assert m.context.dropped == []
    assert m.context.round == 2


async def test_unsupported_objection_ignored():
    a = DebateAgents(fatal_for={"Idea 0"}, supported=False)
    m = machine(a)
    await m.run()
    assert m.context.dropped == [] and m.context.round == 1


async def test_validate_survivors_over_budget_asks_approval():
    a = DebateAgents()
    m = machine(a)
    m.guard = BudgetGuard("discover", state={"cost_usd": 0.19})
    assert await m.run() == DState.WAITING_APPROVAL
    assert any(e["type"] == "approval_required" for e in a.events)
    await m.approve(False)
    assert await m.run() == DState.DONE
    assert len(m.context.results) >= 1


def test_rank_order():
    def r(v, s, score, c=0.8):
        return {"verdict": {"verdict": v, "stability": s, "score": score, "confidence": c}}

    rows = [
        r("PIVOT", "STABLE", 65),
        r("GO", "BORDERLINE", 72),
        r("INSUFFICIENT_EVIDENCE", "STABLE", None),
        r("GO", "STABLE", 71),
        r("NO-GO", "STABLE", 40),
        r("GO", "STABLE", 80),
    ]
    ordered = [
        (x["verdict"]["verdict"], x["verdict"]["stability"], x["verdict"]["score"]) for x in sorted(rows, key=rank_key)
    ]
    assert ordered == [
        ("GO", "STABLE", 80),
        ("GO", "STABLE", 71),
        ("GO", "BORDERLINE", 72),
        ("PIVOT", "STABLE", 65),
        ("NO-GO", "STABLE", 40),
        ("INSUFFICIENT_EVIDENCE", "STABLE", None),
    ]

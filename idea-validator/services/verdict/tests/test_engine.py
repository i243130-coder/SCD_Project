"""Mandatory M11 tests (Section 9.5) — one test per bullet, at minimum."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ivcommon.schemas.core import (
    DIMENSIONS,
    ChallengeAdjustment,
    DimensionScore,
    StudentProfile,
    VerdictRequest,
    WhatIfRequest,
)
from src.config import load_config, validate_weights
from src.engine import (
    apply_challenge,
    decide,
    overall_confidence,
    redistribute,
    threshold_label,
    whatif,
)

CFG = load_config()
PORTFOLIO = {"demand_pain": 15, "competition": 15, "differentiation": 15, "feasibility": 25, "risk": 10, "learning": 20}


def make_req(
    scores: dict[str, float | None] | float = 3.5,
    *,
    conf: dict[str, float] | float = 0.8,
    goal: str = "portfolio",
    n_sources: int = 5,
    n_platforms: int = 2,
    effort: float | None = 100,
    blocker: str | None = None,
    duplicate_of: str | None = None,
    hours: float = 10,
    weeks: int = 12,
    team: int = 2,
    adjustments: list[ChallengeAdjustment] | None = None,
    override: dict | None = None,
) -> VerdictRequest:
    if not isinstance(scores, dict):
        scores = {d: scores for d in DIMENSIONS}
    if not isinstance(conf, dict):
        conf = {d: conf for d in DIMENSIONS}
    out = []
    for d in DIMENSIONS:
        s = scores[d]
        extra: dict = {}
        if d == "feasibility":
            extra["effort_hours"] = effort
        if d == "risk":
            extra["blocker"] = blocker
        if d == "competition":
            extra["duplicate_of"] = duplicate_of
        out.append(
            DimensionScore(
                dimension=d,
                score=s,
                confidence=0.0 if s is None else conf[d],
                evidence_ids=[] if s is None else [f"card_{d}#c0"],
                reason="test",
                rubric_version=f"{d}@v1",
                model="rule",
                abstained=s is None,
                extra=extra,
            )
        )
    profile = StudentProfile(
        user_id="u1",
        skills=["python"],
        hours_per_week=hours,
        weeks_available=weeks,
        team_size=team,
        compute="laptop",
        goal=goal,
    )  # type: ignore[arg-type]
    return VerdictRequest(
        scores=out,
        profile=profile,
        n_sources=n_sources,
        n_platforms=n_platforms,
        challenge_adjustments=adjustments or [],
        config_override=override,
    )


WORKED = {
    "demand_pain": 3.5,
    "competition": 2.0,
    "differentiation": 3.0,
    "feasibility": 4.0,
    "risk": 3.5,
    "learning": 4.5,
}


# ---------------------------------------------------------------- evidence gate
def test_evidence_gate_two_sources_is_insufficient():
    v = decide(make_req(n_sources=2, n_platforms=2), CFG)
    assert v.verdict == "INSUFFICIENT_EVIDENCE"
    assert v.gates["evidence"] == "fail"
    assert "have 2 on 2" in v.missing[0] and ">=3 independent sources" in v.missing[0]


def test_evidence_gate_three_sources_one_platform_is_insufficient():
    v = decide(make_req(n_sources=3, n_platforms=1), CFG)
    assert v.verdict == "INSUFFICIENT_EVIDENCE"
    assert "on >=2 platforms" in v.missing[0] and "have 3 on 1" in v.missing[0]


def test_evidence_gate_three_sources_two_platforms_passes():
    v = decide(make_req(n_sources=3, n_platforms=2), CFG)
    assert v.gates["evidence"] == "pass"
    assert v.verdict != "INSUFFICIENT_EVIDENCE" or not v.missing[0].startswith("need")


# ---------------------------------------------------------------- feasibility gate
def test_feasibility_gate_effort_equal_available_passes():
    v = decide(make_req(effort=240), CFG)  # 10 h/w * 12 w * 2 people = 240
    assert v.gates["feasibility"] == "pass"


def test_feasibility_gate_effort_plus_one_is_no_go_with_gap():
    v = decide(make_req(effort=241), CFG)
    assert v.verdict == "NO-GO"
    assert v.gates["feasibility"] == "fail"
    assert v.gate_details["feasibility"] == "needs 241h, has 240h (gap 1h)"
    assert v.score is None
    assert v.gates["risk"] == "not_run" and v.gates["duplicate"] == "not_run"


# ---------------------------------------------------------------- risk gate
def test_risk_gate_blocker_is_no_go_naming_it():
    v = decide(make_req(blocker="gives medical advice"), CFG)
    assert v.verdict == "NO-GO"
    assert v.gates["risk"] == "fail"
    assert "gives medical advice" in v.gate_details["risk"]


# ---------------------------------------------------------------- duplicate gate
def test_duplicate_gate_low_differentiation_is_no_go_naming_product():
    scores = {d: 3.5 for d in DIMENSIONS} | {"differentiation": 2.9}
    v = decide(make_req(scores, duplicate_of="Eventbrite"), CFG)
    assert v.verdict == "NO-GO"
    assert v.gates["duplicate"] == "fail"
    assert "Eventbrite" in v.gate_details["duplicate"]


def test_duplicate_gate_differentiation_three_passes():
    scores = {d: 3.5 for d in DIMENSIONS} | {"differentiation": 3.0}
    v = decide(make_req(scores, duplicate_of="Eventbrite"), CFG)
    assert v.gates["duplicate"] == "pass"


# ---------------------------------------------------------------- order
def test_gate_order_evidence_before_risk():
    v = decide(make_req(n_sources=1, n_platforms=1, blocker="illegal"), CFG)
    assert v.verdict == "INSUFFICIENT_EVIDENCE"
    assert v.gates["evidence"] == "fail" and v.gates["risk"] == "not_run"


# ---------------------------------------------------------------- abstained
def test_abstained_dimension_is_insufficient_and_listed():
    scores: dict[str, float | None] = {d: 4.0 for d in DIMENSIONS}
    scores["competition"] = None
    v = decide(make_req(scores), CFG)
    assert v.verdict == "INSUFFICIENT_EVIDENCE"
    assert v.missing == ["no evidence for competition"]
    assert v.score is None


# ---------------------------------------------------------------- thresholds
def test_threshold_exactly_70_is_go():
    v = decide(make_req(3.5), CFG)
    assert v.score == pytest.approx(70.0)
    assert v.verdict == "GO"


def test_threshold_69_99_is_pivot():
    scores = {d: 3.5 for d in DIMENSIONS} | {"risk": 3.495}  # risk weight 10 -> -0.01
    v = decide(make_req(scores), CFG)
    assert v.score == pytest.approx(69.99)
    assert v.verdict == "PIVOT"
    assert threshold_label(69.99, [], CFG) == "PIVOT"


def test_threshold_exactly_50_is_pivot():
    v = decide(make_req(2.5), CFG)
    assert v.score == pytest.approx(50.0)
    assert v.verdict == "PIVOT"


def test_threshold_49_99_is_no_go():
    scores = {d: 2.5 for d in DIMENSIONS} | {"risk": 2.495}
    v = decide(make_req(scores), CFG)
    assert v.score == pytest.approx(49.99)
    assert v.verdict == "NO-GO"
    assert threshold_label(49.99, [], CFG) == "NO-GO"


# ---------------------------------------------------------------- floor
def test_floor_breach_turns_go_into_pivot_and_names_weakest():
    scores = {d: 5.0 for d in DIMENSIONS} | {"competition": 1.4}
    v = decide(make_req(scores), CFG)
    assert v.score is not None and v.score >= 70
    assert v.verdict == "PIVOT"
    assert v.weakest_dimension == "competition"


def test_floor_exactly_1_5_is_go():
    scores = {d: 5.0 for d in DIMENSIONS} | {"competition": 1.5}
    assert decide(make_req(scores), CFG).verdict == "GO"


def test_learning_zero_does_not_breach_floor():
    scores = {d: 5.0 for d in DIMENSIONS} | {"learning": 0.0}
    v = decide(make_req(scores), CFG)
    assert v.score == pytest.approx(80.0)
    assert v.verdict == "GO"


# ---------------------------------------------------------------- confidence
def test_confidence_exactly_half_proceeds():
    v = decide(make_req(5.0, conf=2 / 7, n_sources=5), CFG)  # 0.7*(2/7) + 0.3*1 = 0.5
    assert v.confidence == pytest.approx(0.5)
    assert v.verdict == "GO"


def test_confidence_just_below_half_is_insufficient():
    m = (0.4999 - 0.3) / 0.7
    v = decide(make_req(5.0, conf=m, n_sources=5), CFG)
    assert v.confidence == pytest.approx(0.4999)
    assert v.verdict == "INSUFFICIENT_EVIDENCE"
    assert v.missing[0].startswith("overall confidence 0.50 < 0.5") or "< 0.5" in v.missing[0]


def test_confidence_formula_numeric():
    conf = {
        "demand_pain": 0.9,
        "competition": 0.6,
        "differentiation": 0.7,
        "feasibility": 0.8,
        "risk": 0.5,
        "learning": 0.9,
    }
    mean = sum(conf.values()) / 6
    assert overall_confidence(conf, 3, CFG) == pytest.approx(0.7 * mean + 0.3 * 0.6)
    assert overall_confidence(conf, 9, CFG) == pytest.approx(0.7 * mean + 0.3 * 1.0)


# ---------------------------------------------------------------- weights
def test_every_preset_sums_to_100():
    for goal, w in CFG.weights.items():
        assert sum(w.values()) == pytest.approx(100), goal


def test_bad_config_is_rejected():
    bad = {"weights": {"portfolio": PORTFOLIO | {"learning": 19}}}
    with pytest.raises(ValueError):
        load_config(override=bad)
    with pytest.raises(ValueError):
        validate_weights(PORTFOLIO | {"risk": 11})


# ---------------------------------------------------------------- sensitivity
def test_weight_redistribution_keeps_sum_and_is_proportional():
    w = redistribute(PORTFOLIO, "feasibility", -0.20)
    assert sum(w.values()) == pytest.approx(100)
    assert w["feasibility"] == pytest.approx(20)
    assert w["demand_pain"] == pytest.approx(16)
    assert w["risk"] == pytest.approx(10 + 5 * 10 / 75)
    assert w["learning"] == pytest.approx(20 + 5 * 20 / 75)
    # ratios between the other dimensions are unchanged
    assert w["learning"] / w["risk"] == pytest.approx(PORTFOLIO["learning"] / PORTFOLIO["risk"])


def test_sensitivity_has_exactly_14_runs():
    v = decide(make_req(4.0), CFG)
    assert v.sensitivity["runs"] == 14
    assert len(v.sensitivity["all_runs"]) == 14


def test_sensitivity_reports_known_flip():
    v = decide(make_req(WORKED), CFG)
    perts = {f["perturbation"]: f for f in v.sensitivity["flips"]}
    assert "weight feasibility -20%" in perts
    assert perts["weight feasibility -20%"]["verdict"] == "PIVOT"
    assert v.stability == "BORDERLINE"


def test_far_from_threshold_is_stable():
    v = decide(make_req(5.0), CFG)
    assert v.stability == "STABLE" and v.sensitivity["flipped"] == 0


# ---------------------------------------------------------------- challenge
def test_challenge_one_objection():
    s, c = apply_challenge(
        {"risk": 4.0}, {"risk": 0.8}, [ChallengeAdjustment(dimension="risk", accepted_objections=1)], CFG
    )
    assert s["risk"] == pytest.approx(3.5)
    assert c["risk"] == pytest.approx(0.7)


def test_challenge_three_objections_capped():
    s, c = apply_challenge(
        {"risk": 4.0}, {"risk": 0.8}, [ChallengeAdjustment(dimension="risk", accepted_objections=3)], CFG
    )
    assert s["risk"] == pytest.approx(3.0)  # capped at -1.0
    assert c["risk"] == pytest.approx(0.5)


def test_challenge_confidence_never_below_zero():
    s, c = apply_challenge(
        {"risk": 0.2}, {"risk": 0.15}, [ChallengeAdjustment(dimension="risk", accepted_objections=3)], CFG
    )
    assert c["risk"] == 0.0
    assert s["risk"] == 0.0


def test_challenge_applied_through_decide():
    req = make_req(4.0, adjustments=[ChallengeAdjustment(dimension="competition", accepted_objections=1)])
    v = decide(req, CFG)
    comp = next(s for s in v.scores if s.dimension == "competition")
    assert comp.score == pytest.approx(3.5)
    assert comp.confidence == pytest.approx(0.7)


# ---------------------------------------------------------------- what-if
def test_whatif_empty_when_already_go():
    assert decide(make_req(5.0), CFG).what_would_make_go == []


def test_whatif_returns_smallest_delta():
    # all 3.4 -> S = 68 (PIVOT). Feasibility (w=25) or learning (w=20) +0.5 reach >= 70.
    v = decide(make_req(3.4), CFG)
    assert v.verdict == "PIVOT"
    deltas = [o.delta for o in v.what_would_make_go if o.dimension is not None]
    assert deltas and min(deltas) == pytest.approx(0.5)
    assert all(o.new_verdict == "GO" for o in v.what_would_make_go)
    no_pref = decide(make_req(3.4, override={"whatif": {"prefer_stable": False}}), CFG)
    assert no_pref.what_would_make_go[0].delta == pytest.approx(0.5)
    assert [o.delta for o in no_pref.what_would_make_go] == sorted(o.delta for o in no_pref.what_would_make_go)


def test_whatif_prefers_stable_go():
    # startup weights; learning (w=5) is least confident, so its -1 run moves S by only 1 point.
    # demand +0.5 -> S=70.5 is GO but BORDERLINE; demand +1.0 -> 73 is a STABLE GO and must be ranked first.
    conf = {d: 0.9 for d in DIMENSIONS} | {"learning": 0.6}
    v = decide(make_req(3.4, conf=conf, goal="startup"), CFG)
    opts = v.what_would_make_go
    assert opts[0].new_stability == "STABLE"
    stabs = [o.new_stability for o in opts]
    assert stabs == sorted(stabs, key=lambda s: s != "STABLE")
    no_pref = decide(make_req(3.4, conf=conf, goal="startup", override={"whatif": {"prefer_stable": False}}), CFG)
    assert no_pref.what_would_make_go[0].delta <= opts[0].delta


def test_whatif_gate_fix_for_feasibility():
    v = decide(make_req(4.5, effort=300), CFG)  # has 240, gap 60h over 12 weeks * 2 people = 2.5 h/week
    changes = [o.change for o in v.what_would_make_go]
    assert any(c.startswith("add 2.5 hours/week") for c in changes)
    assert any(c.startswith("reduce scope by 60 hours") for c in changes)


def test_whatif_gate_fix_for_duplicate():
    scores = {d: 4.5 for d in DIMENSIONS} | {"differentiation": 2.0}
    v = decide(make_req(scores, duplicate_of="Notion"), CFG)
    assert any(o.change == "raise differentiation to 3" for o in v.what_would_make_go)


# ---------------------------------------------------------------- determinism
def test_determinism_byte_identical():
    req = make_req(WORKED)
    assert decide(req, CFG).model_dump_json() == decide(req, CFG).model_dump_json()


# ---------------------------------------------------------------- worked example 9.6
def test_worked_example():
    req = make_req(WORKED, conf=0.8, n_sources=5)
    v = decide(req, CFG)
    assert v.confidence == pytest.approx(0.86)
    assert v.score == pytest.approx(70.5)
    assert v.verdict == "GO"
    assert v.stability == "BORDERLINE"
    flip = next(f for f in v.sensitivity["flips"] if f["perturbation"] == "weight feasibility -20%")
    assert flip["score"] == pytest.approx(69.87, abs=0.01)
    assert v.versions == {"engine": "m11@v1", "rubrics": "r1", "profile_weights": "w1"}

    w = whatif(WhatIfRequest(**req.model_dump(), score_overrides={"competition": 3.0}), CFG)
    assert w.score == pytest.approx(73.5)
    assert w.verdict == "GO"
    run = next(r for r in w.sensitivity["all_runs"] if r["perturbation"] == "weight feasibility -20%")
    assert run["score"] == pytest.approx(73.07, abs=0.01)
    assert run["verdict"] == "GO"


# ---------------------------------------------------------------- no LLM
def test_no_llm_in_verdict_service():
    src = Path(__file__).resolve().parents[1] / "src"
    pattern = re.compile(
        r"(import\s+(openai|anthropic|httpx|requests|litellm)|from\s+(openai|anthropic|httpx|"
        r"requests|litellm|ivcommon\.llm|ivcommon\.http)\b|\bllm\b)",
        re.I,
    )
    offenders = [
        f"{p.name}:{i}"
        for p in src.rglob("*.py")
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == [], offenders

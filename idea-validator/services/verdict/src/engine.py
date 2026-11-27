"""M11 Verdict Engine — plain, deterministic Python. NO language model is involved here (rule 6).

Implements Section 9.3 exactly as pure functions:
  0. challenge adjustments  1. hard gates (evidence, feasibility, risk, duplicate)  1b. abstained dims
  2. weighted score  3. confidence  4. thresholds + floor  5. sensitivity (14 runs)  6. what-would-make-GO

Floats are kept at full precision. Comparisons use a value rounded to 9 decimals so that values that are
mathematically on a threshold (e.g. C = 0.5) are not pushed off it by binary floating-point noise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from ivcommon.schemas.core import (
    DIMENSIONS,
    ChallengeAdjustment,
    DimensionScore,
    Flip,
    StudentProfile,
    Verdict,
    VerdictRequest,
    WhatIfOption,
    WhatIfRequest,
)

from .config import VerdictConfig, deep_merge, validate_weights

EPS_DECIMALS = 9


def _r(x: float) -> float:
    return round(x, EPS_DECIMALS)


def _fmt(x: float) -> str:
    return f"{x:g}" if abs(x - round(x)) > 1e-9 else str(int(round(x)))


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Inputs:
    """Everything the core decision needs, after challenge adjustments."""

    score: dict[str, float | None]
    conf: dict[str, float]
    goal: str
    hours_per_week: float
    weeks_available: int
    team_size: int
    n_sources: int
    n_platforms: int
    effort_hours: float | None
    blocker: str | None
    duplicate_of: str | None
    weights: dict[str, float]

    @property
    def available_hours(self) -> float:
        return self.hours_per_week * self.weeks_available * self.team_size

    def with_score(self, d: str, value: float) -> Inputs:
        s = dict(self.score)
        s[d] = value
        return replace(self, score=s)


@dataclass
class Core:
    label: str
    score: float | None
    confidence: float
    gates: dict[str, str]
    gate_details: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    weakest: str | None = None
    failed_gate: str | None = None


def build_inputs(
    scores: list[DimensionScore],
    profile: StudentProfile,
    n_sources: int,
    n_platforms: int,
    weights: dict[str, float],
    adjustments: list[ChallengeAdjustment],
    cfg: VerdictConfig,
) -> Inputs:
    by_dim = {s.dimension: s for s in scores}
    score: dict[str, float | None] = {}
    conf: dict[str, float] = {}
    for d in DIMENSIONS:
        s = by_dim.get(d)
        if s is None or s.abstained or s.score is None:
            score[d], conf[d] = None, 0.0 if s is None else s.confidence
        else:
            score[d], conf[d] = s.score, s.confidence
    score, conf = apply_challenge(score, conf, adjustments, cfg)

    def extra(dim: str, key: str) -> Any:
        s = by_dim.get(dim)  # type: ignore[call-overload]
        return None if s is None else s.extra.get(key)

    effort = extra("feasibility", "effort_hours")
    dup = extra("competition", "duplicate_of") or extra("differentiation", "duplicate_of")
    return Inputs(
        score=score,
        conf=conf,
        goal=profile.goal,
        hours_per_week=profile.hours_per_week,
        weeks_available=profile.weeks_available,
        team_size=profile.team_size,
        n_sources=n_sources,
        n_platforms=n_platforms,
        effort_hours=None if effort is None else float(effort),
        blocker=extra("risk", "blocker"),
        duplicate_of=dup,
        weights=dict(weights),
    )


# --------------------------------------------------------------------------- step 0


def apply_challenge(
    score: dict[str, float | None], conf: dict[str, float], adjustments: list[ChallengeAdjustment], cfg: VerdictConfig
) -> tuple[dict[str, float | None], dict[str, float]]:
    score, conf = dict(score), dict(conf)
    c = cfg.challenge
    for adj in adjustments:
        k = adj.accepted_objections
        if k <= 0:
            continue
        d = adj.dimension
        cur = score.get(d)
        if cur is not None:
            score[d] = max(0.0, cur - min(c.max_penalty, c.score_penalty_per_objection * k))
        conf[d] = max(0.0, conf.get(d, 0.0) - c.confidence_penalty_per_objection * k)
    return score, conf


# --------------------------------------------------------------------------- steps 1-4


def weighted_score(score: dict[str, float | None], weights: dict[str, float]) -> float:
    return sum(weights[d] * float(score[d] or 0.0) for d in DIMENSIONS) / 5


def overall_confidence(conf: dict[str, float], n_sources: int, cfg: VerdictConfig) -> float:
    c = cfg.confidence
    mean = sum(conf[d] for d in DIMENSIONS) / len(DIMENSIONS)
    return c.w_mean_dim * mean + c.w_sources * min(1.0, n_sources / c.sources_saturation)


def threshold_label(S: float, floor_breach: list[str], cfg: VerdictConfig) -> str:
    t = cfg.thresholds
    if _r(S) >= t["T_go"] and not floor_breach:
        return "GO"
    if _r(S) >= t["T_no"]:
        return "PIVOT"
    return "NO-GO"


def weakest_dimension(inp: Inputs, cfg: VerdictConfig) -> str | None:
    cands = [d for d in cfg.floor_dimensions if inp.score[d] is not None]
    if not cands:
        return None
    # lowest score; tie-break: higher weight first, then lower confidence, then declaration order
    return min(cands, key=lambda d: (inp.score[d], -inp.weights[d], inp.conf[d], DIMENSIONS.index(d)))  # type: ignore[arg-type,index]


def core_decide(inp: Inputs, cfg: VerdictConfig) -> Core:
    gates = {"evidence": "not_run", "feasibility": "not_run", "risk": "not_run", "duplicate": "not_run"}
    conf_all = overall_confidence(inp.conf, inp.n_sources, cfg)
    eg = cfg.evidence_gate

    # 1. hard gates, in order; the first failure decides
    if inp.n_sources < eg.min_sources or inp.n_platforms < eg.min_platforms:
        gates["evidence"] = "fail"
        msg = (
            f"need >={eg.min_sources} independent sources on >={eg.min_platforms} platforms, "
            f"have {inp.n_sources} on {inp.n_platforms}"
        )
        return Core("INSUFFICIENT_EVIDENCE", None, conf_all, gates, {"evidence": msg}, [msg], failed_gate="evidence")
    gates["evidence"] = "pass"

    available = inp.available_hours
    if inp.effort_hours is not None and _r(inp.effort_hours) > _r(available):
        gates["feasibility"] = "fail"
        gap = inp.effort_hours - available
        msg = f"needs {_fmt(inp.effort_hours)}h, has {_fmt(available)}h (gap {_fmt(gap)}h)"
        return Core("NO-GO", None, conf_all, gates, {"feasibility": msg}, failed_gate="feasibility")
    gates["feasibility"] = "pass"

    if inp.blocker is not None:
        gates["risk"] = "fail"
        return Core("NO-GO", None, conf_all, gates, {"risk": f"blocker: {inp.blocker}"}, failed_gate="risk")
    gates["risk"] = "pass"

    diff = inp.score["differentiation"]
    if inp.duplicate_of is not None and (diff is None or _r(diff) < cfg.duplicate_gate.min_differentiation_to_override):
        gates["duplicate"] = "fail"
        return Core(
            "NO-GO",
            None,
            conf_all,
            gates,
            {"duplicate": f"existing product: {inp.duplicate_of}"},
            failed_gate="duplicate",
        )
    gates["duplicate"] = "pass"

    # 1b. abstained dimensions
    abstained = [d for d in DIMENSIONS if inp.score[d] is None]
    if abstained:
        return Core("INSUFFICIENT_EVIDENCE", None, conf_all, gates, {}, [f"no evidence for {d}" for d in abstained])

    # 2. weighted score, 3. confidence
    S = weighted_score(inp.score, inp.weights)
    if _r(conf_all) < cfg.confidence.min_confidence:
        lowest = sorted(DIMENSIONS, key=lambda d: (inp.conf[d], DIMENSIONS.index(d)))[:2]
        missing = [f"overall confidence {conf_all:.2f} < {cfg.confidence.min_confidence}"]
        missing += [f"low confidence on {d} ({inp.conf[d]:.2f})" for d in lowest]
        return Core("INSUFFICIENT_EVIDENCE", None, conf_all, gates, {}, missing, weakest_dimension(inp, cfg))

    # 4. thresholds + floor
    floor = cfg.thresholds["floor"]
    breach = [d for d in cfg.floor_dimensions if _r(inp.score[d]) < floor]  # type: ignore[arg-type]
    label = threshold_label(S, breach, cfg)
    return Core(
        label,
        S,
        conf_all,
        gates,
        {"floor": f"below floor: {', '.join(breach)}"} if breach else {},
        weakest=weakest_dimension(inp, cfg),
    )


# --------------------------------------------------------------------------- step 5


def redistribute(weights: dict[str, float], d: str, f: float) -> dict[str, float]:
    """Change w[d] by factor (1+f); share the difference proportionally over the others (sum stays 100)."""
    w = dict(weights)
    new = weights[d] * (1 + f)
    diff = new - weights[d]
    others = [o for o in DIMENSIONS if o != d]
    total_o = sum(weights[o] for o in others)
    w[d] = new
    for o in others:
        w[o] = weights[o] - (diff * weights[o] / total_o if total_o else 0.0)
    return w


def least_confident(inp: Inputs) -> str:
    cands = [d for d in DIMENSIONS if inp.score[d] is not None] or list(DIMENSIONS)
    return min(cands, key=lambda d: (inp.conf[d], -inp.weights[d], DIMENSIONS.index(d)))


def sensitivity(inp: Inputs, base: Core, cfg: VerdictConfig) -> dict[str, Any]:
    sc = cfg.sensitivity
    runs: list[Flip] = []
    for d in DIMENSIONS:
        for f in (+sc.weight_change, -sc.weight_change):
            r = core_decide(replace(inp, weights=redistribute(inp.weights, d, f)), cfg)
            runs.append(
                Flip(
                    perturbation=f"weight {d} {'+' if f > 0 else '-'}{_fmt(abs(f) * 100)}%",
                    verdict=r.label,
                    score=r.score,
                )
            )  # type: ignore[arg-type]
    lc = least_confident(inp)
    for delta in (+sc.score_change, -sc.score_change):
        cur = inp.score[lc]
        if cur is None:
            r = core_decide(inp, cfg)
        else:
            r = core_decide(inp.with_score(lc, min(5.0, max(0.0, cur + delta))), cfg)
        runs.append(
            Flip(
                perturbation=f"score {lc} {'+' if delta > 0 else '-'}{_fmt(abs(delta))}", verdict=r.label, score=r.score
            )
        )  # type: ignore[arg-type]
    flips = [r for r in runs if r.verdict != base.label]
    return {
        "runs": len(runs),
        "flipped": len(flips),
        "flips": [f.model_dump() for f in flips],
        "all_runs": [r.model_dump() for r in runs],
        "least_confident": lc,
    }


def stability_of(sens: dict[str, Any]) -> str:
    return "BORDERLINE" if sens["flipped"] else "STABLE"


# --------------------------------------------------------------------------- step 6


def _evaluate(inp: Inputs, cfg: VerdictConfig) -> tuple[Core, str]:
    c = core_decide(inp, cfg)
    return c, stability_of(sensitivity(inp, c, cfg))


def what_would_make_go(inp: Inputs, base: Core, cfg: VerdictConfig) -> list[WhatIfOption]:
    if base.label == "GO":
        return []
    wc = cfg.whatif
    cands: list[tuple[bool, float, float, WhatIfOption]] = []

    # dimension changes (only meaningful once gates are not blocking)
    for d in DIMENSIONS:
        cur = inp.score[d]
        if cur is None or cur >= 5:
            continue
        steps = []
        k = 1
        while _r(k * wc.step) < _r(5 - cur):
            steps.append(k * wc.step)
            k += 1
        steps.append(5 - cur)
        found_go = False
        for delta in steps:
            r, stab = _evaluate(inp.with_score(d, cur + delta), cfg)
            if r.label != "GO":
                continue
            if not found_go or stab == "STABLE":
                opt = WhatIfOption(
                    change=f"raise {d} by {_fmt(delta)} (to {_fmt(cur + delta)})",
                    dimension=d,  # type: ignore[arg-type]
                    delta=delta,
                    new_score=r.score or 0.0,
                    new_verdict="GO",
                    new_stability=stab,
                )  # type: ignore[arg-type]
                cands.append((stab == "STABLE", delta, r.score or 0.0, opt))
            found_go = True
            # the smallest GO is always kept; with prefer_stable we keep looking for the smallest STABLE GO
            if stab == "STABLE" or not wc.prefer_stable:
                break

    # gate fixes with exact numbers
    if base.failed_gate == "feasibility" and inp.effort_hours is not None:
        gap = inp.effort_hours - inp.available_hours
        per_week = math.ceil(gap / (inp.weeks_available * inp.team_size) * 10) / 10
        fixes = [
            (
                f"add {_fmt(per_week)} hours/week (to {_fmt(inp.hours_per_week + per_week)})",
                replace(inp, hours_per_week=inp.hours_per_week + per_week),
            ),
            (
                f"reduce scope by {_fmt(gap)} hours (to {_fmt(inp.available_hours)}h)",
                replace(inp, effort_hours=inp.available_hours),
            ),
        ]
        for text, new_inp in fixes:
            r, stab = _evaluate(new_inp, cfg)
            opt = WhatIfOption(
                change=text,
                dimension="feasibility",
                delta=0,
                new_score=r.score or 0.0,
                new_verdict=r.label,
                new_stability=stab,
            )  # type: ignore[arg-type]
            cands.append((stab == "STABLE", 0.0, r.score or 0.0, opt))
    if base.failed_gate == "duplicate":
        target = cfg.duplicate_gate.min_differentiation_to_override
        cur = inp.score["differentiation"] or 0.0
        r, stab = _evaluate(inp.with_score("differentiation", max(cur, target)), cfg)
        opt = WhatIfOption(
            change=f"raise differentiation to {_fmt(target)}",
            dimension="differentiation",
            delta=max(0.0, target - cur),
            new_score=r.score or 0.0,
            new_verdict=r.label,  # type: ignore[arg-type]
            new_stability=stab,
        )  # type: ignore[arg-type]
        cands.append((stab == "STABLE", max(0.0, target - cur), r.score or 0.0, opt))

    def key(c: tuple[bool, float, float, WhatIfOption]) -> tuple[Any, ...]:
        stable, delta, score, opt = c
        return ((not stable) if wc.prefer_stable else False, _r(delta), -score, opt.change)

    return [c[3] for c in sorted(cands, key=key)[: wc.max_options]]


# --------------------------------------------------------------------------- public API


def resolve_config(cfg: VerdictConfig, override: dict[str, Any] | None) -> VerdictConfig:
    if not override:
        return cfg
    return VerdictConfig.model_validate(deep_merge(cfg.model_dump(), override))


def decide(req: VerdictRequest, cfg: VerdictConfig, *, weights: dict[str, float] | None = None) -> Verdict:
    cfg = resolve_config(cfg, req.config_override)
    w = weights or cfg.weights[req.profile.goal]
    validate_weights(w)
    inp = build_inputs(req.scores, req.profile, req.n_sources, req.n_platforms, w, req.challenge_adjustments, cfg)
    return _verdict_from_inputs(req, inp, cfg)


def _verdict_from_inputs(req: VerdictRequest, inp: Inputs, cfg: VerdictConfig) -> Verdict:
    base = core_decide(inp, cfg)
    sens = sensitivity(inp, base, cfg)
    options = what_would_make_go(inp, base, cfg) if req.include_what_if else []
    # scores on the card reflect the challenge adjustments
    adjusted = []
    for s in req.scores:
        new = s.model_copy()
        if inp.score.get(s.dimension) is not None and s.score is not None:
            new.score = inp.score[s.dimension]
        new.confidence = inp.conf.get(s.dimension, s.confidence)
        adjusted.append(new)
    return Verdict(
        idea_id=req.idea_id,
        version=req.version,
        run_id=req.run_id,
        verdict=base.label,  # type: ignore[arg-type]
        stability=stability_of(sens),  # type: ignore[arg-type]
        score=base.score,
        confidence=base.confidence,
        gates=base.gates,  # type: ignore[arg-type]
        gate_details=base.gate_details,
        weights=inp.weights,  # type: ignore[arg-type]
        thresholds=dict(cfg.thresholds),
        scores=adjusted,
        weakest_dimension=base.weakest,  # type: ignore[arg-type]
        missing=base.missing,
        what_would_make_go=options,
        sensitivity=sens,
        versions={
            "engine": cfg.engine_version,
            "rubrics": req.rubric_set_version,
            "profile_weights": cfg.weights_version,
        },
    )


def whatif(req: WhatIfRequest, cfg: VerdictConfig) -> Verdict:
    """Steps 0-6 with a hypothetical override. Never persisted."""
    cfg = resolve_config(cfg, req.config_override)
    profile = req.profile.model_copy(update=req.profile_overrides) if req.profile_overrides else req.profile
    w = req.weight_overrides or cfg.weights[profile.goal]
    validate_weights(dict(w))
    inp = build_inputs(req.scores, profile, req.n_sources, req.n_platforms, dict(w), req.challenge_adjustments, cfg)
    for d, v in req.score_overrides.items():
        inp = inp.with_score(d, min(5.0, max(0.0, float(v))))
    return _verdict_from_inputs(req, inp, cfg)

"""Verdict config (ConfigMap `verdict-config`). Refuses to load if a preset does not sum to 100."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, model_validator

DIMS = ("demand_pain", "competition", "differentiation", "feasibility", "risk", "learning")


class ConfidenceCfg(BaseModel):
    w_mean_dim: float = 0.7
    w_sources: float = 0.3
    sources_saturation: float = 5
    min_confidence: float = 0.5


class EvidenceGateCfg(BaseModel):
    min_sources: int = 3
    min_platforms: int = 2


class DuplicateGateCfg(BaseModel):
    min_differentiation_to_override: float = 3.0


class ChallengeCfg(BaseModel):
    score_penalty_per_objection: float = 0.5
    max_penalty: float = 1.0
    confidence_penalty_per_objection: float = 0.1


class SensitivityCfg(BaseModel):
    weight_change: float = 0.20
    score_change: float = 1.0


class WhatIfCfg(BaseModel):
    step: float = 0.5
    prefer_stable: bool = True
    max_options: int = 3


class VerdictConfig(BaseModel):
    engine_version: str
    weights_version: str
    weights: dict[str, dict[str, float]]
    thresholds: dict[str, float]
    floor_dimensions: list[str]
    confidence: ConfidenceCfg = ConfidenceCfg()
    evidence_gate: EvidenceGateCfg = EvidenceGateCfg()
    duplicate_gate: DuplicateGateCfg = DuplicateGateCfg()
    challenge: ChallengeCfg = ChallengeCfg()
    sensitivity: SensitivityCfg = SensitivityCfg()
    whatif: WhatIfCfg = WhatIfCfg()

    @model_validator(mode="after")
    def _check(self) -> VerdictConfig:
        for goal, w in self.weights.items():
            validate_weights(w, f"preset {goal}")
        for k in ("T_go", "T_no", "floor"):
            if k not in self.thresholds:
                raise ValueError(f"thresholds.{k} missing")
        if self.thresholds["T_no"] > self.thresholds["T_go"]:
            raise ValueError("T_no must be <= T_go")
        bad = [d for d in self.floor_dimensions if d not in DIMS]
        if bad:
            raise ValueError(f"unknown floor dimensions {bad}")
        return self


def validate_weights(w: dict[str, float], what: str = "weights") -> None:
    if set(w) != set(DIMS):
        raise ValueError(f"{what} must have exactly the six dimensions, got {sorted(w)}")
    if any(v < 0 for v in w.values()):
        raise ValueError(f"{what} has a negative weight")
    if abs(sum(w.values()) - 100) > 1e-6:
        raise ValueError(f"{what} sums to {sum(w.values())}, must be 100")


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def default_config_path() -> Path:
    env = os.environ.get("VERDICT_CONFIG")
    if env:
        return Path(env)
    for p in (Path("/config/verdict.yaml"), Path(__file__).resolve().parents[3] / "config" / "verdict.yaml"):
        if p.exists():
            return p
    raise FileNotFoundError("verdict.yaml not found (set VERDICT_CONFIG)")


def load_config(path: str | Path | None = None, override: dict[str, Any] | None = None) -> VerdictConfig:
    raw = yaml.safe_load(Path(path or default_config_path()).read_text())
    if override:
        raw = deep_merge(raw, override)
    return VerdictConfig.model_validate(raw)

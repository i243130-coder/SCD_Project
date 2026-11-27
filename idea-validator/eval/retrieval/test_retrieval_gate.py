"""CI retrieval gate (R-M6): fails if hybrid+rerank Recall@5 or MRR drops more than 0.02 below the baseline."""

import json
from pathlib import Path

import yaml
from metrics import evaluate

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
TOLERANCE = 0.02


def test_at_least_20_queries():
    assert len(yaml.safe_load((HERE / "queries.yaml").read_text())["queries"]) >= 20


def test_hybrid_rerank_not_below_baseline():
    base = json.loads((HERE / "baseline.json").read_text())
    res = evaluate(ROOT / base["fixture"], HERE / "queries.yaml")["hybrid_rerank"]
    assert res["recall@5"] >= base["recall@5"] - TOLERANCE, res
    assert res["mrr"] >= base["mrr"] - TOLERANCE, res

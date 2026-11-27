import json
from datetime import UTC, date, datetime
from pathlib import Path

from src.cluster import cluster
from src.gaps import find_gaps
from src.main import compute
from src.trends import classify, monthly_series, slope

CARDS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[3] / "eval/retrieval/fixtures/cards.jsonl").read_text().splitlines()
]


def test_slope_and_classification_edges():
    assert slope([1, 2, 3, 4]) > 0.05
    assert slope([5, 5, 5, 5]) == 0.0
    assert classify(0.0501, 10, 50) == "rising"
    assert classify(0.05, 10, 50) == "flat"
    assert classify(-0.05, 10, 50) == "flat"
    assert classify(0.05, 50, 50) == "saturated"
    assert classify(0.2, 50, 50) == "rising"


def test_monthly_series_counts():
    s = monthly_series(
        [
            {"source": "producthunt", "published_at": "2026-10-03"},
            {"source": "hackernews", "published_at": "2026-10-20"},
        ],
        date(2026, 11, 1),
        3,
    )
    assert [x["month"] for x in s] == ["2026-09", "2026-10", "2026-11"]
    assert s[1] == {"month": "2026-10", "launches": 1, "mentions": 1}


def test_clustering_deterministic():
    assert cluster(CARDS) == cluster(CARDS)


def test_gap_extraction_from_fixture():
    edu = [c for c in CARDS if c["niche"] == "home"]
    gaps = find_gaps(edu, "home")
    assert gaps and all(g["evidence_ids"][0].endswith("#c0") for g in gaps)


def test_compute_names_niches_with_status():
    out = compute(CARDS, datetime(2026, 11, 1, tzinfo=UTC))
    assert {n["status"] for n in out["niches"]} <= {"rising", "flat", "saturated"}
    assert all(n["name"] and n["keywords"] for n in out["niches"])

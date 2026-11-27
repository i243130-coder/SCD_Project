import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import main
from src.freshness import stats
from src.index import MemoryIndex, chunk_text
from src.search import rrf, search_chunks

FIXTURE = Path(__file__).resolve().parents[3] / "eval" / "retrieval" / "fixtures" / "cards.jsonl"
CARDS = [json.loads(line) for line in FIXTURE.read_text().splitlines()]


@pytest.fixture(scope="module")
def idx():
    i = MemoryIndex()
    i.add_cards(CARDS)
    return i


def test_chunks_keep_card_id():
    i = MemoryIndex()
    long = dict(CARDS[0], text=" ".join(["word"] * 1000))
    i.add_cards([long])
    assert len(i.chunks) >= 3
    assert all(c.chunk_id.startswith(f"{long['id']}#c") and c.card_id == long["id"] for c in i.chunks)
    assert [c.chunk_id for c in i.chunks][:2] == [f"{long['id']}#c0", f"{long['id']}#c1"]


def test_chunk_overlap():
    parts = chunk_text(" ".join(str(n) for n in range(800)), size=350, overlap=50)
    assert parts[1].split()[0] == "300"


def test_exact_product_name_found(idx):
    top = search_chunks(idx, "FlakeHunter", k=3)
    assert top[0].name == "FlakeHunter"


def test_problem_description_found(idx):
    top = search_chunks(idx, "university society event sign ups are a mess", k=5)
    assert {c.niche for c in top[:2]} == {"campus-events"}


def test_filters_source_and_date(idx):
    top = search_chunks(idx, "tool", k=10, filters={"source": ["github"]})
    assert top and all(c.source == "github" for c in top)
    dated = search_chunks(idx, "tool", k=30, filters={"date_from": "2026-05-01", "date_to": "2026-06-30"})
    assert dated and all(c.published_at and "2026-05-01" <= c.published_at.isoformat() <= "2026-06-30" for c in dated)
    assert all(c.niche == "edtech" for c in search_chunks(idx, "tool", k=10, filters={"niche": ["edtech"]}))


def test_rrf_fusion():
    fused = [i for i, _ in rrf([1, 2, 3], [3, 1, 4])]
    assert fused[:2] == [1, 3]


def test_stats_coverage(idx):
    s = stats(idx)
    assert s["total_cards"] == len(CARDS)
    assert set(s["sources"]) == {"hackernews", "github", "producthunt", "yc"}


def test_api_search_lookup(monkeypatch, idx):
    main.app.state.index = idx
    main.app.state.redis = None
    c = TestClient(main.app)
    r = c.post("/search", json={"query": "late invoice reminders for freelancers", "k": 3}).json()
    assert r["cache_hit"] is False and len(r["results"]) == 3
    ev = r["results"][0]
    assert "#c" in ev["evidence_id"] and ev["quote"] and ev["url"]
    assert len({e["card_id"] for e in r["results"]}) == 3  # one evidence item per card
    lk = c.post("/evidence/lookup", json={"ids": [ev["evidence_id"], "card_nope#c0"]}).json()
    assert ev["evidence_id"] in lk["found"] and lk["missing"] == ["card_nope#c0"]
    assert c.get("/cards/card_nope").status_code == 404

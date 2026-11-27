import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_dataset import build  # noqa: E402
from common import DIMS, labelled_ideas, norm  # noqa: E402
from split import split  # noqa: E402

CARDS = [{"id": f"card_{i}", "name": f"Product {i}", "summary": f"does thing {i}"} for i in range(40)]


def fake_search(q, k):
    return [{"evidence_id": f"card_e{j}#c0", "card_id": f"card_e{j}", "quote": "q"} for j in range(k)]


def test_build_excludes_tuning_set_ideas():
    excl = {norm("Product 3 does thing 3")}
    rows = build(CARDS, fake_search, 60, exclude=excl)
    assert all(r["idea_id"] != "card_3" for r in rows)
    assert {r["dimension"] for r in rows} == set(DIMS)
    assert {r["evidence_strength"] for r in rows} == {0, 1, 2, 3}


def test_labelled_file_is_read():
    assert norm("RSVP and attendance tool for university robotics societies, web only") in labelled_ideas()


def test_split_by_idea_and_checked_go_to_test():
    rows = []
    for i in range(20):
        for d in DIMS[:3]:
            rows.append(
                {
                    "idea_id": f"card_{i}",
                    "idea": f"P{i}: x",
                    "dimension": d,
                    "evidence": [],
                    "label": {"score": 3, "confidence": 0.5, "evidence_ids": [], "reason": ""},
                    "checked": i < 3,
                }
            )
    train, test = split(rows)
    tr, te = {r["idea_id"] for r in train}, {r["idea_id"] for r in test}
    assert not tr & te
    assert {"card_0", "card_1", "card_2"} <= te
    assert abs(len(te) / 20 - 0.2) <= 0.05

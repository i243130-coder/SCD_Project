from fastapi.testclient import TestClient

from src import main
from src.agents import extract_fields_rule, novelty_ok, template_ideas


def no_kb(monkeypatch):
    async def empty(q, k=5):
        return []

    monkeypatch.setattr(main, "kb_search", empty)
    monkeypatch.delenv("HOSTED_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODE", "live")


def test_idea_without_gap_evidence_rejected(monkeypatch):
    no_kb(monkeypatch)
    monkeypatch.setattr(
        main,
        "template_ideas",
        lambda p: [
            {"title": "A", "one_liner": "x", "problem": "p", "customer": "c", "gap_evidence_ids": []},
            {"title": "B", "one_liner": "x", "problem": "p", "customer": "c", "gap_evidence_ids": ["card_1#c0"]},
        ],
    )
    out = TestClient(main.app).post("/generate", json={"gaps": [], "count": 2}).json()
    assert [i["title"] for i in out] == ["B"]


def test_template_ideas_cite_gaps():
    ideas = template_ideas(
        {"gaps": [{"description": "RSVPs are painful", "evidence_ids": ["card_1#c0"], "niche_id": "n"}]}
    )
    assert ideas[0]["gap_evidence_ids"] == ["card_1#c0"]


def test_novelty_rejects_renamed_copy():
    assert not novelty_ok(
        {"title": "Eventbrite ticketing platform", "one_liner": ""}, ["Eventbrite ticketing platform"]
    )
    assert novelty_ok(
        {"title": "Society RSVP helper", "one_liner": "for robotics clubs"}, ["Eventbrite ticketing platform"]
    )


def test_extract_fields_rule():
    f = extract_fields_rule("A mobile app for university robotics societies")
    assert f["platform"] == "mobile" and f["customer"].startswith("university") and f["scope"] is None


def test_suggest_change_wording(monkeypatch):
    no_kb(monkeypatch)
    r = (
        TestClient(main.app)
        .post("/suggest_change", json={"dimension": "feasibility", "delta": 0.5, "change": "raise"})
        .json()
    )
    assert "one core feature" in r["change"]

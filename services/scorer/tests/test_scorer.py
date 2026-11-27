import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from ivcommon.metrics import FALLBACKS
from ivcommon.schemas.core import ScoreRequest
from src import main
from src.backends import RuleBackend, build_messages

EV = [
    {
        "evidence_id": "card_a#c0",
        "card_id": "card_a",
        "quote": "q",
        "source": "hackernews",
        "url": "https://x/a",
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
]
REQ = {
    "rubric": "demand_pain@v1",
    "dimension": "demand_pain",
    "idea": {"text": "RSVP tool"},
    "evidence": EV,
    "features": {"n_sources": 3, "complaint_count": 2},
}


class Scripted:
    def __init__(self, name, outputs):
        self.name, self.outputs, self.calls = name, list(outputs), 0

    async def generate(self, req, rubric_text):
        self.calls += 1
        return self.outputs.pop(0), {}


def client(primary, fallback=None):
    main.app.state.primary = primary
    main.app.state.fallback = fallback or RuleBackend()
    return TestClient(main.app)


def test_valid_output():
    out = json.dumps({"score": 3.5, "confidence": 0.7, "evidence_ids": ["card_a#c0"], "reason": "r"})
    r = client(Scripted("scorer-lora@v1", [out])).post("/score", json=REQ).json()
    assert r["score"] == 3.5 and r["model"] == "scorer-lora@v1" and not r["abstained"]


def test_invalid_json_retry_then_fallback_logged():
    before = FALLBACKS.labels("demand_pain")._value.get()
    p = Scripted("scorer-lora@v1", ["not json", "{still bad"])
    fb = Scripted(
        "hosted:test", [json.dumps({"score": 4, "confidence": 0.6, "evidence_ids": ["card_a#c0"], "reason": "ok"})]
    )
    r = client(p, fb).post("/score", json=REQ).json()
    assert p.calls == 2  # first try + exactly one retry
    assert r["model"] == "hosted:test" and r["extra"]["fallback"] is True and r["score"] == 4
    assert FALLBACKS.labels("demand_pain")._value.get() == before + 1


def test_fake_evidence_ids_removed_and_abstain():
    out = json.dumps({"score": 5, "confidence": 0.9, "evidence_ids": ["card_fake#c9"], "reason": "made up"})
    r = client(Scripted("m", [out])).post("/score", json=REQ).json()
    assert r["evidence_ids"] == [] and r["abstained"] and r["score"] is None and r["confidence"] == 0


def test_no_evidence_abstains_with_rule_backend():
    r = client(RuleBackend()).post("/score", json=REQ | {"evidence": []}).json()
    assert r["abstained"] and r["score"] is None


def test_prompt_wraps_data_and_has_rubric():
    msgs = build_messages(ScoreRequest.model_validate(REQ), "5: great")
    assert "<<<DATA" in msgs[1]["content"] and "untrusted" in msgs[0]["content"] and "5: great" in msgs[0]["content"]


def test_unknown_rubric_422():
    assert client(RuleBackend()).post("/score", json=REQ | {"rubric": "nope@v9"}).status_code == 422

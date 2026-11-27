from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from ivcommon.schemas.core import DimensionScore, EvidenceItem, StudentProfile
from src import features as F
from src import main

P = StudentProfile(
    user_id="u",
    skills=["python", "react"],
    hours_per_week=10,
    weeks_available=12,
    team_size=2,
    compute="laptop",
    goal="portfolio",
    interests=["ml"],
)


def ev(i, src="hackernews", quote="Is there a tool to track RSVPs? frustrated with spreadsheets"):
    return EvidenceItem(
        evidence_id=f"card_{i}#c0",
        card_id=f"card_{i}",
        quote=quote,
        source=src,
        url="https://x",
        retrieved_at=datetime.now(UTC),
        published_at=date(2026, 10, 1),
    )


async def fake_score(req):
    # returns one real id and one invented id; the feasibility "model" also estimates effort
    extra = {"effort_hours": 5000} if req.dimension == "feasibility" else {}
    return DimensionScore(
        dimension=req.dimension,
        score=3.5,
        confidence=0.7,
        evidence_ids=[req.evidence[0].evidence_id, "card_invented#c0"],
        reason="r",
        rubric_version=req.rubric,
        model="fake",
        extra=extra,
    )


def body(evidence, idea="A web dashboard for university clubs to manage RSVPs with login"):
    return {
        "idea": {"text": idea},
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "profile": P.model_dump(),
    }


def client():
    main.app.state.score_fn = fake_score
    return TestClient(main.app)


def test_features_demand():
    f = F.demand([ev(1), ev(2, "github", "an open source RSVP project")], today=date(2026, 11, 1))
    assert f["n_sources"] == 2 and f["n_platforms"] == 2 and f["complaint_count"] == 1 and f["recency_days"] == 31


def test_effort_heuristic_components():
    hours, comps = F.effort_hours("mobile app with login and ML recommendations")
    assert set(comps) >= {"mobile", "auth", "ml"} and hours == 40 + 60 + 20 + 80 + 40


def test_risk_blocker():
    _, flags = F.risk("An app that gives medical advice and dosage for kids")
    assert "medical_advice" in flags and "minors" in flags


def test_fake_ids_removed():
    r = client().post("/score/demand", json=body([ev(1), ev(2)])).json()
    assert r[0]["evidence_ids"] == ["card_1#c0"]


def test_no_evidence_abstains():
    r = client().post("/score/risk", json=body([])).json()
    assert r[0]["abstained"] and r[0]["score"] is None


def test_competition_returns_two_dims_feasibility_returns_effort():
    c = client()
    assert [d["dimension"] for d in c.post("/score/competition", json=body([ev(1)])).json()] == [
        "competition",
        "differentiation",
    ]
    feas = c.post("/score/feasibility", json=body([ev(1)])).json()
    assert [d["dimension"] for d in feas] == ["feasibility", "learning"]
    heur = feas[0]["extra"]["effort_heuristic"]
    assert feas[0]["extra"]["effort_hours"] == 2 * heur  # model's 5000h is bounded by 2x the heuristic


def test_risk_blocker_in_extra():
    r = client().post("/score/risk", json=body([ev(1)], "A chatbot that gives medical advice")).json()
    assert r[0]["extra"]["blocker"] == "medical_advice"


def test_unknown_scorer_404():
    assert client().post("/score/magic", json=body([ev(1)])).status_code == 404

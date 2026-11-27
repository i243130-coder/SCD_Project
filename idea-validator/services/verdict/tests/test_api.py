from fastapi.testclient import TestClient

from src.main import app
from tests.test_engine import WORKED, make_req

client = TestClient(app)


def test_health_and_ready():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").status_code == 200


def test_post_verdict_worked_example():
    r = client.post("/verdict", json=make_req(WORKED).model_dump(mode="json"))
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "GO" and body["stability"] == "BORDERLINE"


def test_post_whatif_bad_weights_422():
    req = make_req(WORKED).model_dump(mode="json")
    req["weight_overrides"] = {
        "demand_pain": 50,
        "competition": 10,
        "differentiation": 10,
        "feasibility": 10,
        "risk": 10,
        "learning": 5,
    }
    assert client.post("/whatif", json=req).status_code == 422

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src import main
from src.drift import report, tvd
from src.traces import TraceStore


def rec(step, parent=None, kind="tool_call", **kw):
    return {
        "run_id": "run_1",
        "step_id": step,
        "parent_step": parent,
        "agent": "a",
        "kind": kind,
        "input": "i",
        "output": "o",
        "ts": datetime.now(UTC).isoformat(),
        **kw,
    }


def test_trace_roundtrip_tree(tmp_path):
    main.app.state.store = TraceStore(tmp_path)
    c = TestClient(main.app)
    assert c.post(
        "/trace", json=[rec(1), rec(2, 1, cost_usd=0.01), rec(3, kind="decision", cache_hit=True)]
    ).json() == {"stored": 3}
    body = c.get("/runs/run_1/trace").json()
    assert (
        body["summary"]["n_steps"] == 3 and body["summary"]["cost_usd"] == 0.01 and body["summary"]["cache_hits"] == 1
    )
    assert len(body["tree"]) == 2 and body["tree"][0]["children"][0]["step_id"] == 2
    assert c.get("/runs/missing/trace").status_code == 404
    assert "run_1" in c.get("/dashboard").text


def test_registry_lists_versions():
    r = TestClient(main.app).get("/registry").json()
    assert "rubrics/risk@v1.yaml" in r["files"] and r["rubric_set"].startswith("r")


def test_drift_flags_large_shift():
    r = report({"niches": {"a": {"cards": 1}}}, {"niches": {"a": {"cards": 5}}}, ["GO"] * 10, ["NO-GO"] * 10)
    assert r["flagged"] and r["verdict_distribution"]["tvd"] == 1.0
    assert r["niche_coverage"]["a"] == {"before": 1, "after": 5}
    assert tvd({"GO": 0.5, "PIVOT": 0.5}, {"GO": 0.5, "PIVOT": 0.5}) == 0

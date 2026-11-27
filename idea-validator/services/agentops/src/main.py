"""M13 AgenticOps: POST /trace, GET /runs/{id}/trace, GET /registry, GET /dashboard, GET /drift/latest, POST /eval/run."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from ivcommon.health import health_router
from ivcommon.metrics import metrics_router
from ivcommon.schemas.core import TraceRecord

from .drift import report
from .traces import TraceStore

ROOT = Path(__file__).resolve().parents[3]
app = FastAPI(title="agentops (M13)")
app.include_router(health_router("agentops"))
app.include_router(metrics_router())
DRIFT_DIR = Path(os.environ.get("DRIFT_DIR", "/traces/drift"))


def store() -> TraceStore:
    if getattr(app.state, "store", None) is None:
        app.state.store = TraceStore(os.environ.get("TRACE_DIR", "/traces"))
    return app.state.store  # type: ignore[no-any-return]


@app.post("/trace")
async def post_trace(recs: list[TraceRecord]) -> dict[str, int]:
    return {"stored": store().append(recs)}


@app.get("/runs/{run_id}/trace")
async def get_trace(run_id: str) -> dict[str, Any]:
    tree = store().tree(run_id)
    if not tree:
        raise HTTPException(404, "no trace")
    return {"summary": store().summary(run_id), "tree": tree}


@app.get("/registry")
async def registry() -> dict[str, Any]:
    lock = Path(os.environ.get("REGISTRY_LOCK", str(ROOT / "registry.lock")))
    if not lock.exists():
        raise HTTPException(404, "registry.lock missing")
    return json.loads(lock.read_text())  # type: ignore[no-any-return]


@app.post("/drift")
async def post_drift(body: dict[str, Any]) -> dict[str, Any]:
    r = report(
        body.get("prev_stats", {}),
        body.get("cur_stats", {}),
        body.get("prev_verdicts", []),
        body.get("cur_verdicts", []),
    )
    DRIFT_DIR.mkdir(parents=True, exist_ok=True)
    (DRIFT_DIR / "latest.json").write_text(json.dumps(r, indent=2))
    return r


@app.get("/drift/latest")
async def drift_latest() -> dict[str, Any]:
    p = DRIFT_DIR / "latest.json"
    if not p.exists():
        raise HTTPException(404, "no drift report yet")
    return json.loads(p.read_text())  # type: ignore[no-any-return]


@app.post("/eval/run", status_code=202)
async def eval_run() -> dict[str, str]:
    return {
        "status": "the evaluation harness runs as the Kubernetes Job eval-job (kubectl apply -f k8s/base/jobs/eval-job.yaml)"
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    rows = "".join(
        f"<tr><td>{r}</td><td>{s['n_steps']}</td><td>{s['cost_usd']}</td><td>{s['latency_ms']}</td>"
        f"<td>{s['cache_hits']}</td><td>{s['errors']}</td></tr>"
        for r in store().runs()[-50:]
        for s in [store().summary(r)]
    )
    return (
        "<html><head><title>AgenticOps</title></head><body><h1>Runs (fallback dashboard; Grafana is the main one)"
        "</h1><table border=1><tr><th>run</th><th>steps</th><th>cost $</th><th>latency ms</th><th>cache hits</th>"
        f"<th>errors</th></tr>{rows}</table></body></html>"
    )

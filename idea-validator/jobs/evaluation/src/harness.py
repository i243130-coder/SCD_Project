"""Evaluation harness (§15, R-G13): runs the deployed system (through the gateway) on eval/labelled/ideas.yaml ->
verdict agreement, 4x4 confusion matrix, false-GO count + behaviour checks. Writes eval/results/{date}.json and
compares with eval/results/baseline.json. Runs as the Kubernetes Job `eval-job` and nightly from Jenkins."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

LABELS = ["GO", "PIVOT", "NO-GO", "INSUFFICIENT_EVIDENCE"]
ROOT = Path(os.environ.get("EVAL_ROOT", Path(__file__).resolve().parents[3]))


def confusion(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    m = {h: {s: 0 for s in LABELS} for h in LABELS}
    for human, system in pairs:
        m[human][system] += 1
    n = len(pairs) or 1
    agree = sum(m[label][label] for label in LABELS)
    false_go = sum(m[h]["GO"] for h in LABELS if h != "GO")
    return {
        "matrix": m,
        "agreement": round(agree / n, 4),
        "n": len(pairs),
        "false_go": false_go,
        "false_go_on_expert_no_go": m["NO-GO"]["GO"],
    }


def run_system(base: str, ideas: list[dict[str, Any]], timeout_s: float = 180) -> list[dict[str, Any]]:
    c = httpx.Client(base_url=base, timeout=30)
    email, pw = f"eval-{uuid.uuid4().hex[:8]}@eval.invalid", uuid.uuid4().hex
    tok = c.post("/auth/register", json={"email": email, "password": pw}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    out = []
    for item in ideas:
        c.put("/profile", json=item["profile"], headers=h).raise_for_status()
        rid = c.post("/validate", json={"idea_text": item["idea"]}, headers=h).json()["run_id"]
        t0, run = time.time(), {}
        while time.time() - t0 < timeout_s:
            run = c.get(f"/runs/{rid}", headers=h).json()
            if run.get("state") in ("DONE", "FAILED"):
                break
            if run.get("state") == "WAITING_ANSWER":
                for q in run.get("questions", []):
                    c.post(f"/runs/{rid}/answer", json={"question_id": q["id"], "skip": True}, headers=h)
            if run.get("state") == "WAITING_APPROVAL":
                c.post(f"/runs/{rid}/approve", json={"approve": False}, headers=h)
            time.sleep(2)
        v = run.get("verdict") or {}
        out.append(
            {
                "id": item["id"],
                "human": item["human_verdict"],
                "system": v.get("verdict", "FAILED"),
                "stability": v.get("stability"),
                "score": v.get("score"),
                "evidence_ok": all("#c" in i for s in v.get("scores", []) for i in s.get("evidence_ids", [])),
                "cost_usd": run.get("budget", {}).get("cost_usd"),
                "state": run.get("state"),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://gateway:8000"))
    ap.add_argument("--labelled", default=str(ROOT / "eval/labelled/ideas.yaml"))
    ap.add_argument("--out", default=str(ROOT / "eval/results"))
    ap.add_argument("--max-drop", type=float, default=0.05)
    a = ap.parse_args()
    data = yaml.safe_load(Path(a.labelled).read_text())
    ideas = [i for i in data.get("ideas", []) if i.get("human_verdict") in LABELS]
    if not ideas:
        print("no labelled ideas yet (TODO(human): label eval/labelled/ideas.yaml)")
        return 2
    rows = run_system(a.gateway, ideas)
    res = {
        "date": datetime.now(UTC).isoformat(),
        "rubric_set": json.loads((ROOT / "registry.lock").read_text())["rubric_set"],
        **confusion([(r["human"], r["system"]) for r in rows if r["system"] in LABELS]),
        "failed_runs": sum(1 for r in rows if r["system"] not in LABELS),
        "behaviour": {"evidence_cited_real_ids": all(r["evidence_ok"] for r in rows)},
        "rows": rows,
    }
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{datetime.now(UTC):%Y-%m-%d}.json").write_text(json.dumps(res, indent=2))
    base = outdir / "baseline.json"
    print(json.dumps({k: res[k] for k in ("agreement", "false_go", "n", "failed_runs")}))
    if base.exists():
        b = json.loads(base.read_text())
        if b.get("rubric_set") != res["rubric_set"]:
            print("rubric set differs from baseline: comparison labelled, not gated")
            return 0
        if res["agreement"] < b["agreement"] - a.max_drop or res["false_go"] > b["false_go"]:
            print(
                f"REGRESSION vs baseline: agreement {b['agreement']} -> {res['agreement']}, false-GO {b['false_go']} -> {res['false_go']}"
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

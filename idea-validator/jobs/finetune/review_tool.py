"""Human review page (FastAPI): shows idea, evidence, rubric and the draft label; a HUMAN accepts or edits it.
Only this tool sets "checked": true — the agent never does.
    python jobs/finetune/review_tool.py --member "Member 1"   then open http://127.0.0.1:8765"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import uvicorn
from common import ROOT, read_jsonl, write_jsonl
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

DRAFTS = Path(__file__).parent / "data/raw/drafts.jsonl"
app = FastAPI()
MEMBER = {"name": ""}


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    rows = read_jsonl(DRAFTS)
    todo = [i for i, r in enumerate(rows) if not r["checked"]]
    done = len(rows) - len(todo)
    if not todo:
        return f"<p>All {len(rows)} reviewed.</p>"
    i = todo[0]
    r = rows[i]
    rubric = html.escape((ROOT / f"rubrics/{r['dimension']}@v1.yaml").read_text())
    ev = "".join(
        f"<li><code>{html.escape(e['evidence_id'])}</code> {html.escape(e['quote'])}</li>" for e in r["evidence"]
    )
    lab = r["label"]
    return f"""<h2>{done} checked / {len(rows)} (need >= 60) &mdash; reviewer: {html.escape(MEMBER["name"])}</h2>
<h3>{html.escape(r["dimension"])}: {html.escape(r["idea"])}</h3><ul>{ev or "<li>(no evidence: should abstain)</li>"}</ul>
<form method=post action=/save><input type=hidden name=i value={i}>
score <input name=score value="{"" if lab.get("score") is None else lab["score"]}"> (empty = abstain)
confidence <input name=confidence value="{lab.get("confidence", 0)}"><br>
evidence ids <input size=80 name=ids value="{html.escape(",".join(lab.get("evidence_ids", [])))}"><br>
reason <textarea name=reason cols=100>{html.escape(lab.get("reason", ""))}</textarea><br><button>Accept</button></form>
<details><summary>rubric</summary><pre>{rubric}</pre></details>"""


@app.post("/save")
def save(
    i: int = Form(), score: str = Form(""), confidence: float = Form(0), ids: str = Form(""), reason: str = Form("")
):
    rows = read_jsonl(DRAFTS)
    allowed = {e["evidence_id"] for e in rows[i]["evidence"]}
    rows[i]["label"] = {
        "score": float(score) if score.strip() else None,
        "confidence": confidence,
        "evidence_ids": [x.strip() for x in ids.split(",") if x.strip() in allowed],
        "reason": reason,
    }
    rows[i]["checked"], rows[i]["checked_by"] = True, MEMBER["name"]
    write_jsonl(DRAFTS, rows)
    return RedirectResponse("/", status_code=303)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--member", required=True)
    MEMBER["name"] = ap.parse_args().member
    print(json.dumps({"drafts": str(DRAFTS)}))
    uvicorn.run(app, host="127.0.0.1", port=8765)

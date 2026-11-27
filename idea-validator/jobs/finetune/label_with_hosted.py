"""Draft labels with the hosted model using each rubric -> drafts.jsonl with "checked": false.
The hosted model's output is only a DRAFT; humans check >= 60 with review_tool.py.
    python jobs/finetune/label_with_hosted.py   (needs LLM_BASE_URL / LLM_API_KEY / HOSTED_MODEL)"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from common import ROOT, read_jsonl, write_jsonl

sys.path.insert(0, str(ROOT / "libs/common"))
from ivcommon.llm import DATA_SYSTEM_LINE, LLMClient, data_block  # noqa: E402

HERE = Path(__file__).parent


async def main() -> None:
    llm = LLMClient()
    rows = read_jsonl(HERE / "data/raw/candidates.jsonl")
    out = []
    for r in rows:
        rubric = (ROOT / f"rubrics/{r['dimension']}@v1.yaml").read_text()
        ev = "\n".join(f"[{e['evidence_id']}] {e['quote']}" for e in r["evidence"])
        msgs = [
            {
                "role": "system",
                "content": f"Score with this rubric. {DATA_SYSTEM_LINE} Reply JSON only: "
                '{"score": 0-5|null, "confidence": 0-1, "evidence_ids": [], "reason": ""}\n' + rubric,
            },
            {"role": "user", "content": f"IDEA: {data_block(r['idea'])}\nEVIDENCE:\n{data_block(ev)}"},
        ]
        try:
            label = json.loads((await llm.chat(msgs)).content)
        except Exception as e:  # keep going; failures are visible in the file
            label = {"score": None, "confidence": 0, "evidence_ids": [], "reason": f"draft failed: {e!r}"}
        out.append({**r, "label": label, "draft_model": llm.model, "checked": False, "checked_by": None})
    write_jsonl(HERE / "data/raw/drafts.jsonl", out)
    print(f"{len(out)} drafts written; now hand-check >= 60 with review_tool.py")


if __name__ == "__main__":
    asyncio.run(main())

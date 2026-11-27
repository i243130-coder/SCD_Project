"""Group-aware 80/20 split BY IDEA (seed fixed): one idea never appears in both train and test.
Hand-checked examples go to the test/eval set. Writes train.jsonl, test.jsonl, checked_ids.txt, dataset_card.md."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from pathlib import Path
from typing import Any

from common import labelled_ideas, norm, read_jsonl, to_chat, write_jsonl

HERE = Path(__file__).parent
SEED = 42


def split(
    rows: list[dict[str, Any]], test_frac: float = 0.2, seed: int = SEED
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    excl = labelled_ideas()
    rows = [r for r in rows if norm(r["idea"].split(":", 1)[-1]) not in excl and norm(r["idea"]) not in excl]
    checked_ideas = {r["idea_id"] for r in rows if r.get("checked")}
    others = sorted({r["idea_id"] for r in rows} - checked_ideas)
    random.Random(seed).shuffle(others)
    n_test_target = int(test_frac * len({r["idea_id"] for r in rows}))
    test_ideas = checked_ideas | set(others[: max(0, n_test_target - len(checked_ideas))])
    train = [
        r
        for r in rows
        if r["idea_id"] not in test_ideas
        and r.get("label", {}).get("score") is not None
        or (r["idea_id"] not in test_ideas and r.get("label"))
    ]
    test = [r for r in rows if r["idea_id"] in test_ideas]
    return train, test


def main() -> None:
    rows = read_jsonl(HERE / "data/raw/drafts.jsonl")
    train, test = split(rows)
    write_jsonl(HERE / "data/train.jsonl", [to_chat(r) for r in train])
    write_jsonl(HERE / "data/test.jsonl", [to_chat(r) | {"checked": r.get("checked", False)} for r in test])
    checked = [r for r in rows if r.get("checked")]
    (HERE / "data/checked_ids.txt").write_text(
        "".join(f"{r['idea_id']}|{r['dimension']}|{r['checked_by']}\n" for r in checked)
    )
    lv = Counter(
        (r["dimension"], None if r["label"].get("score") is None else int(round(r["label"]["score"]))) for r in rows
    )
    h = hashlib.sha256((HERE / "data/train.jsonl").read_bytes()).hexdigest()[:12]
    lines = [
        "# Dataset card",
        "",
        f"- examples: {len(rows)} (train {len(train)}, test {len(test)})",
        f"- hand-checked: {len(checked)} (all in test)",
        f"- train sha256: {h}",
        "",
        "| dimension | level | n |",
        "|---|---|---|",
    ]
    lines += [
        f"| {d} | {lvl} | {n} |"
        for (d, lvl), n in sorted(lv.items(), key=lambda x: (x[0][0], -1 if x[0][1] is None else x[0][1]))
    ]
    (HERE / "dataset_card.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:5]))


if __name__ == "__main__":
    main()

"""Grid search T_go / T_no / floor on harness results (needs per-idea scores saved by the harness).
Objective = agreement - 3 x false-GO rate (calling GO on an expert NO-GO is worst). Reports a held-out 25 % split.
    python eval/tune.py eval/results/2026-12-01.json
TODO(human): run after labelling; save tuning_before.json / tuning_after.json; update config/verdict.yaml + weights_version."""

import itertools
import json
import random
import sys

rows = [r for r in json.load(open(sys.argv[1]))["rows"] if r.get("score") is not None]
if not rows:
    sys.exit("no scored rows")
random.Random(7).shuffle(rows)
cut = max(1, len(rows) // 4)
held, train = rows[:cut], rows[cut:]


def label(score, tg, tn):
    return "GO" if score >= tg else "PIVOT" if score >= tn else "NO-GO"


def objective(rs, tg, tn):
    agree = sum(label(r["score"], tg, tn) == r["human"] for r in rs) / len(rs)
    fgo = sum(label(r["score"], tg, tn) == "GO" and r["human"] != "GO" for r in rs) / len(rs)
    return agree - 3 * fgo, agree, fgo


best = max(
    ((tg, tn) for tg, tn in itertools.product(range(60, 86, 2), range(35, 66, 2)) if tn < tg),
    key=lambda t: objective(train, *t)[0],
)
print(
    json.dumps(
        {
            "best": {"T_go": best[0], "T_no": best[1]},
            "train": objective(train, *best)[1:],
            "held_out": objective(held, *best)[1:],
            "note": "floor tuning needs per-dimension scores",
        }
    )
)

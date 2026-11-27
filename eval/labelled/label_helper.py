"""Interactive labelling helper: shows each unlabelled idea + profile and records a human verdict.
python eval/labelled/label_helper.py --member "Member 1"
"""

import argparse
from pathlib import Path

import yaml

P = Path(__file__).with_name("ideas.yaml")
CHOICES = {"g": "GO", "p": "PIVOT", "n": "NO-GO", "i": "INSUFFICIENT_EVIDENCE"}

ap = argparse.ArgumentParser()
ap.add_argument("--member", required=True)
a = ap.parse_args()
data = yaml.safe_load(P.read_text())
for it in data["ideas"]:
    if a.member in it.get("labelled_by", []):
        continue
    print(f"\n[{it['id']}] {it['idea']}\nprofile: {it['profile']}\ncurrent: {it.get('human_verdict')}")
    c = input("verdict [g/p/n/i, enter=skip]: ").strip().lower()
    if c in CHOICES:
        if it.get("human_verdict") and it["human_verdict"] != CHOICES[c]:
            it["notes"] = (it.get("notes", "") + f" | disagreement: {a.member} said {CHOICES[c]}").strip(" |")
        else:
            it["human_verdict"] = CHOICES[c]
        it.setdefault("labelled_by", []).append(a.member)
P.write_text(yaml.safe_dump(data, sort_keys=False, width=120))

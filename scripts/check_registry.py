"""Prompt & rubric registry check (§15): fails if a file's content changed without a version bump.
`--update` rewrites registry.lock after a deliberate version bump."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "registry.lock"


def current() -> dict[str, dict[str, str]]:
    out = {}
    for p in sorted([*ROOT.glob("prompts/*.md"), *ROOT.glob("rubrics/*.yaml")]):
        m = re.match(r"(.+)@v(\d+)", p.stem)
        if not m:
            raise SystemExit(f"{p.name}: file name must be name@vN")
        out[p.relative_to(ROOT).as_posix()] = {
            "name": m.group(1),
            "version": m.group(2),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
    return out


def rubric_set_version(entries: dict[str, dict[str, str]]) -> str:
    rub = sorted(f"{e['name']}@v{e['version']}" for k, e in entries.items() if k.startswith("rubrics/"))
    return "r" + hashlib.sha256("|".join(rub).encode()).hexdigest()[:8]


def main() -> int:
    cur = current()
    if "--update" in sys.argv or not LOCK.exists():
        LOCK.write_text(json.dumps({"files": cur, "rubric_set": rubric_set_version(cur)}, indent=2) + "\n")
        print("registry.lock written")
        return 0
    locked = json.loads(LOCK.read_text())["files"]
    bad = [f for f, e in cur.items() if f in locked and locked[f]["sha256"] != e["sha256"]]
    if bad:
        print("Content changed without a version bump (copy to name@v{N+1} instead):", ", ".join(bad))
        return 1
    new = [f for f in cur if f not in locked]
    if new:
        print("New prompt/rubric versions not in registry.lock (run with --update):", ", ".join(new))
        return 1
    print(f"registry ok ({len(cur)} files, rubric set {rubric_set_version(cur)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

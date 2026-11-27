"""Export every Pydantic model to schemas/<Name>.json. `--check` fails if they are out of date (CI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libs" / "common"))

from ivcommon import schemas  # noqa: E402


def render() -> dict[str, str]:
    out = {}
    for name in schemas.EXPORTED_MODELS:
        model = getattr(schemas, name)
        out[f"{name}.json"] = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
    return out


def main() -> int:
    check = "--check" in sys.argv
    target = ROOT / "schemas"
    target.mkdir(exist_ok=True)
    stale = []
    for fname, content in render().items():
        p = target / fname
        if check:
            if not p.exists() or p.read_text() != content:
                stale.append(fname)
        else:
            p.write_text(content)
    if stale:
        print("Schemas out of date, run `python scripts/export_schemas.py`:", ", ".join(stale))
        return 1
    print("schemas ok" if check else f"wrote {len(render())} schema files to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

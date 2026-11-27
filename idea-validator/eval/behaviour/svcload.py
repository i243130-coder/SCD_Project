"""Loads each service's `src` package under a unique name so several services can be used in one test process."""

import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_service(name: str):
    pkg = f"svc_{name}"
    if pkg not in sys.modules:
        src = ROOT / "services" / name / "src"
        spec = importlib.util.spec_from_file_location(pkg, src / "__init__.py", submodule_search_locations=[str(src)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg] = mod
        spec.loader.exec_module(mod)
    return lambda sub: importlib.import_module(f"{pkg}.{sub}")


sys.path.insert(0, str(ROOT / "services" / "orchestrator"))  # for tests.fakes

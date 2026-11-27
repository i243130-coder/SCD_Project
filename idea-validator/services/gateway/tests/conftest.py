import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))

import os  # noqa: E402

os.environ.setdefault("JWT_SECRET", "test-secret-not-real")
os.environ.setdefault("PROFILE_URL", "http://profile.test")
os.environ.setdefault("ORCHESTRATOR_URL", "http://orch.test")
os.environ.setdefault("CRITIC_URL", "http://critic.test")
os.environ.setdefault("RATE_AUTH_IP_PER_MIN", "5")

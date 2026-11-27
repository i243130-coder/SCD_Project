import subprocess
import sys
from pathlib import Path

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from src import db
from src.main import app
from src.models.tables import Base
from src.services.cache import cache_key

SERVICE = Path(__file__).resolve().parents[1]

PROFILE = {
    "user_id": "x",
    "skills": ["python", "react"],
    "hours_per_week": 10,
    "weeks_available": 12,
    "team_size": 2,
    "compute": "laptop",
    "goal": "portfolio",
    "interests": ["education"],
}


@pytest.fixture
def client(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    db.init_engine(url)

    async def create():
        eng = create_async_engine(url)
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        await eng.dispose()

    import asyncio

    asyncio.run(create())
    app.state.redis = fakeredis.aioredis.FakeRedis()
    with TestClient(app) as c:
        yield c


def test_register_verify_and_duplicate(client):
    r = client.post("/users", json={"email": "A@x.io", "password": "password1"})
    assert r.status_code == 201
    assert client.post("/users", json={"email": "a@x.io", "password": "password1"}).status_code == 409
    assert client.post("/users/verify", json={"email": "a@x.io", "password": "password1"}).status_code == 200
    assert client.post("/users/verify", json={"email": "a@x.io", "password": "wrongpass"}).status_code == 401
    assert client.post("/users", json={"email": "b@x.io", "password": "short"}).status_code == 422


def test_profile_edit_bumps_version(client):
    uid = client.post("/users", json={"email": "p@x.io", "password": "password1"}).json()["id"]
    v1 = client.put(f"/profiles/{uid}", json=PROFILE).json()
    assert v1["profile_version"] == 1 and v1["user_id"] == uid
    same = client.put(f"/profiles/{uid}", json=PROFILE).json()
    assert same["profile_version"] == 1  # no change -> no bump
    v2 = client.put(f"/profiles/{uid}", json=PROFILE | {"hours_per_week": 20}).json()
    assert v2["profile_version"] == 2
    assert client.get(f"/profiles/{uid}").json()["hours_per_week"] == 20


def test_ideas_versions_verdicts(client):
    uid = client.post("/users", json={"email": "i@x.io", "password": "password1"}).json()["id"]
    idea = client.post("/ideas", json={"user_id": uid, "text": "Event tool for university clubs"}).json()
    assert idea["version"] == 1
    v2 = client.post(f"/ideas/{idea['id']}/versions", json={"text": "narrower", "change_applied": "narrow"}).json()
    assert v2["version"] == 2
    vs = client.get(f"/ideas/{idea['id']}/versions").json()
    assert [v["version"] for v in vs] == [1, 2]
    assert client.get("/ideas", params={"user_id": uid}).json()[0]["versions"] == 2


def test_runs_and_approvals(client):
    r = client.post("/runs", json={"user_id": "u", "kind": "validate"}).json()
    assert r["state"] == "INTAKE"
    p = client.patch(f"/runs/{r['id']}", json={"state": "DONE", "spent_usd": 0.01}).json()
    assert p["state"] == "DONE" and p["finished_at"] is not None
    a = client.post("/approvals", json={"run_id": r["id"], "action": "deep_search", "estimated_cost": 0.03}).json()
    assert a["decision"] == "pending"
    assert client.post(f"/approvals/{a['id']}", json={"approve": False}).json()["decision"] == "declined"


def test_cache_hit_visible(client):
    assert client.get("/cache/verdict:abc").status_code == 404
    client.put("/cache/verdict:abc", json={"verdict": "GO"})
    assert client.get("/cache/verdict:abc").json() == {"verdict": "GO", "cache_hit": True}


def test_cache_key_changes_with_profile_and_rubric_versions():
    base = dict(
        idea_text="An app",
        profile_version=1,
        profile_weights_version="w1",
        rubric_set_version="r1",
        engine_version="m11@v1",
        kb_snapshot_id="s1",
    )
    k = cache_key("verdict", **base)
    assert cache_key("verdict", **base | {"idea_text": "  an   APP "}) == k  # normalised text
    assert cache_key("verdict", **base | {"profile_version": 2}) != k
    assert cache_key("verdict", **base | {"rubric_set_version": "r2"}) != k
    assert cache_key("verdict", **base | {"engine_version": "m11@v2"}) != k
    with pytest.raises(ValueError):
        cache_key("verdict", idea_text="x")


def test_migration_up_down(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    env = {"ALEMBIC_URL": url, "PATH": "/usr/bin:/bin"}
    alembic = [sys.executable, "-m", "alembic"]
    subprocess.run([*alembic, "upgrade", "head"], cwd=SERVICE, env=env, check=True)
    from sqlalchemy import create_engine

    eng = create_engine(url)
    assert {
        "users",
        "profiles",
        "ideas",
        "idea_versions",
        "runs",
        "verdicts",
        "dimension_scores",
        "approvals",
        "conversations",
        "traces_index",
    } <= set(inspect(eng).get_table_names())
    subprocess.run([*alembic, "downgrade", "base"], cwd=SERVICE, env=env, check=True)
    eng.dispose()
    eng = create_engine(url)
    assert "users" not in inspect(eng).get_table_names()

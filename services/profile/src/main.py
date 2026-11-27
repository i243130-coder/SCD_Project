"""M2 Profile, Session and Cache service."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from ivcommon.health import health_router
from ivcommon.metrics import metrics_router

from . import db
from .routes.api import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if db._engine is None:
        db.init_engine()
    if getattr(app.state, "redis", None) is None:
        import redis.asyncio as aioredis

        app.state.redis = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    yield


app = FastAPI(title="profile (M2)", lifespan=lifespan)


async def _db_ok() -> bool:
    assert db._engine is not None
    async with db._engine.connect() as c:
        await c.execute(text("SELECT 1"))
    return True


async def _redis_ok() -> bool:
    return bool(await app.state.redis.ping())


app.include_router(health_router("profile", {"postgres": _db_ok, "redis": _redis_ok}))
app.include_router(metrics_router())
app.include_router(router)

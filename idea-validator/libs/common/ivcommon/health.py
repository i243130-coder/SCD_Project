"""/health (process alive) and /ready (dependencies reachable) router factory (rule 11)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response

ReadyCheck = Callable[[], Awaitable[bool]]


def health_router(service: str, checks: dict[str, ReadyCheck] | None = None) -> APIRouter:
    router = APIRouter()
    checks = checks or {}

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": service}

    @router.get("/ready")
    async def ready(response: Response) -> dict[str, object]:
        results: dict[str, bool] = {}
        for name, check in checks.items():
            try:
                results[name] = bool(await check())
            except Exception:
                results[name] = False
        ok = all(results.values())
        if not ok:
            response.status_code = 503
        return {"status": "ready" if ok else "not_ready", "service": service, "checks": results}

    return router

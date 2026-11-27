"""Prometheus helpers: every service mounts /metrics."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUESTS = Counter("http_requests_total", "HTTP requests", ["service", "path", "status"])
LATENCY = Histogram("agent_latency_seconds", "Latency per agent/step", ["agent"])
CACHE_HITS = Counter("cache_hits_total", "Cache hits", ["kind"])
CACHE_MISSES = Counter("cache_misses_total", "Cache misses", ["kind"])
FALLBACKS = Counter("scorer_fallback_total", "Scorer fallbacks to the hosted model", ["dimension"])
INJECTIONS = Counter("injections_blocked_total", "Instruction-like patterns neutralised", ["where"])
FETCH_BLOCKED = Counter("fetch_blocked_total", "Fetches blocked by allow-list/robots/budget", ["reason"])
APPROVALS = Counter("approvals_total", "Approval prompts", ["decision"])
VERDICT_COST = Histogram(
    "verdict_cost_usd", "Cost per verdict in USD", buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2)
)


def metrics_router() -> APIRouter:
    router = APIRouter()

    @router.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router

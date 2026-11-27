"""call_agent: timeout + exponential back-off retries + trace record + live events for every agent call."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ivcommon.metrics import LATENCY
from ivcommon.tracing import Tracer

T = TypeVar("T")


class AgentFailed(Exception):
    def __init__(self, name: str, attempts: int, last: BaseException | None) -> None:
        super().__init__(f"{name} failed after {attempts} attempts: {last!r}")
        self.name, self.attempts, self.last = name, attempts, last


async def call_agent[T](
    name: str,
    factory: Callable[[], Awaitable[T]],
    *,
    tracer: Tracer,
    emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    timeout_s: float = 30.0,
    retries: int = 2,
    kind: str = "tool_call",
    input: Any = "",
    backoff_s: float = 0.2,
) -> T:
    await emit("agent_start", {"agent": name})
    last: BaseException | None = None
    t0 = time.perf_counter()
    for attempt in range(retries + 1):
        try:
            result = await asyncio.wait_for(factory(), timeout=timeout_s)
            ms = int((time.perf_counter() - t0) * 1000)
            LATENCY.labels(name).observe(ms / 1000)
            cache_hit = (
                bool(getattr(result, "cache_hit", False))
                if not isinstance(result, dict)
                else bool(result.get("cache_hit", False))
            )
            tracer.record(
                name, kind, input, _summ(result), latency_ms=ms, retries=attempt, cache_hit=cache_hit, tool=name
            )
            await emit(
                "tool_call",
                {
                    "agent": name,
                    "latency_ms": ms,
                    "retries": attempt,
                    "cache_hit": cache_hit,
                    "input": str(input)[:120],
                },
            )
            await emit("agent_end", {"agent": name, "ok": True})
            return result
        except (TimeoutError, ConnectionError, OSError) as e:
            last = e
        except Exception as e:  # httpx errors etc. are retried as well
            last = e
        if attempt < retries:
            await asyncio.sleep(backoff_s * (2**attempt))
    ms = int((time.perf_counter() - t0) * 1000)
    tracer.record(name, kind, input, "", latency_ms=ms, retries=retries, error=repr(last), tool=name)
    await emit("agent_end", {"agent": name, "ok": False, "error": str(last)})
    raise AgentFailed(name, retries + 1, last)


def _summ(r: Any) -> Any:
    if hasattr(r, "model_dump"):
        return r.model_dump(mode="json")
    if isinstance(r, list):
        return [x.model_dump(mode="json") if hasattr(x, "model_dump") else x for x in r][:20]
    return r

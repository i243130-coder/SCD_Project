"""Trace emitter: JSON line to stdout + async POST to M13 /trace (best effort)."""

from __future__ import annotations

import itertools
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import httpx

from ivcommon.config import get_settings
from ivcommon.schemas.core import TraceRecord


class Tracer:
    def __init__(self, run_id: str, *, send: bool = True, echo: bool | None = None) -> None:
        self.run_id = run_id
        self.echo = os.environ.get("TRACE_STDOUT", "1") == "1" if echo is None else echo
        self._ids = itertools.count(1)
        self.records: list[TraceRecord] = []
        self.send = send

    def record(
        self, agent: str, kind: str, input: Any, output: Any, *, parent_step: int | None = None, **fields: Any
    ) -> TraceRecord:
        rec = TraceRecord(
            run_id=self.run_id,
            step_id=next(self._ids),
            parent_step=parent_step,
            agent=agent,
            kind=kind,  # type: ignore[arg-type]
            input=_s(input),
            output=_s(output),
            ts=datetime.now(UTC),
            **fields,
        )
        self.records.append(rec)
        if self.echo:
            sys.stdout.write(json.dumps({"trace": rec.model_dump(mode="json")}) + "\n")
        return rec

    async def flush(self) -> None:
        if not self.send or not self.records:
            return
        url = f"{get_settings().agentops_url}/trace"
        try:
            async with httpx.AsyncClient() as c:
                await c.post(url, json=[r.model_dump(mode="json") for r in self.records], timeout=5)
        except Exception:  # tracing must never break a run
            pass


def _s(v: Any) -> str:
    if isinstance(v, str):
        return v[:4000]
    try:
        return json.dumps(v, default=str)[:4000]
    except TypeError:
        return str(v)[:4000]

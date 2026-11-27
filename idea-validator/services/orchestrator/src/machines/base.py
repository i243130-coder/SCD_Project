"""Explicit state machine: a `State` enum + a transition table {state: async handler -> next state}.

The context is persisted (via `persist`) and a `state` event + a trace `decision` record are emitted after
every transition, so a run can resume after WAITING_ANSWER / WAITING_APPROVAL or a restart.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel

from ivcommon.tracing import Tracer

S = TypeVar("S", bound=enum.Enum)
C = TypeVar("C", bound=BaseModel)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
Persist = Callable[[str, BaseModel], Awaitable[None]]


class StateMachine[S: enum.Enum, C: BaseModel]:
    terminal: frozenset[str] = frozenset({"DONE", "FAILED"})
    waiting: frozenset[str] = frozenset({"WAITING_ANSWER", "WAITING_APPROVAL"})

    def __init__(
        self,
        state: S,
        context: C,
        transitions: Mapping[S, Callable[[], Awaitable[S]]],
        *,
        emit: Emit,
        persist: Persist,
        tracer: Tracer,
        max_steps: int = 200,
    ) -> None:
        self.state = state
        self.context = context
        self.transitions = transitions
        self.emit = emit
        self.persist = persist
        self.tracer = tracer
        self.max_steps = max_steps
        self.history: list[str] = [state.name]

    @property
    def done(self) -> bool:
        return self.state.name in self.terminal

    @property
    def paused(self) -> bool:
        return self.state.name in self.waiting

    async def step(self) -> S:
        handler = self.transitions.get(self.state)
        if handler is None:
            raise RuntimeError(f"no transition from {self.state.name}")
        prev = self.state
        try:
            nxt = await handler()
        except Exception as e:  # any unhandled error fails the run, visibly
            self.tracer.record("orchestrator", "decision", prev.name, "FAILED", error=repr(e))
            await self.emit("error", {"state": prev.name, "error": str(e)})
            nxt = type(prev)["FAILED"]
            if hasattr(self.context, "error"):
                self.context.error = str(e)  # type: ignore[attr-defined]
        self.state = nxt
        self.history.append(nxt.name)
        self.tracer.record("orchestrator", "decision", prev.name, nxt.name)
        await self.persist(nxt.name, self.context)
        await self.emit("state", {"from": prev.name, "to": nxt.name})
        return nxt

    async def run(self) -> S:
        """Run until a terminal or waiting state."""
        steps = 0
        while not self.done and not self.paused:
            await self.step()
            steps += 1
            if steps > self.max_steps:
                raise RuntimeError("state machine exceeded max_steps")
        return self.state

    def resume_to(self, state: S) -> None:
        self.state = state
        self.history.append(state.name)

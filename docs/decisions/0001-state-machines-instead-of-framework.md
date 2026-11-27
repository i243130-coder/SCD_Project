# 0001 — Hand-written state machines instead of an agent framework

- **Status:** Accepted
- **Context:** R-M3 requires Discover and Validate to be *testable state machines* with retries, timeouts, budget stops and resumability. Agent frameworks hide control flow, which makes transition tests and replay hard.
- **Options:** (1) LangGraph / CrewAI style framework, (2) a workflow engine (Temporal), (3) a small hand-written `StateMachine` with an explicit `State` enum and a transition table.
- **Decision:** (3). `services/orchestrator/src/machines/base.py` defines the machine; each workflow is a dict `State -> async handler` returning the next state.
- **Why:** each transition is a plain async function we can unit test with fake agents; persistence after every transition is one call; no extra dependency; replay only needs the trace.
- **Cost:** we write retries/timeouts ourselves (`call_agent` with `asyncio.wait_for` + tenacity), ~150 lines.
- **AI use:** Drafted by AI (Claude via Claude Code); TODO(human): review and confirm.

"""TestAgent — a deterministic AgentInterface implementation for testing all phases."""

from __future__ import annotations

import os
from typing import AsyncIterator

from agentrt.adapters.base import (
    AgentEvent,
    AgentInterface,
    AgentResponse,
    AgentTraceStep,
    AttackPayload,
    MemoryRecord,
    ToolCallRecord,
)

# Controlled by TEST_AGENT_MODE env var
_MODES = {"blackbox", "greybox", "trace", "injection"}


def _mode() -> str:
    m = os.environ.get("TEST_AGENT_MODE", "blackbox").lower()
    return m if m in _MODES else "blackbox"


class TestAgent(AgentInterface):
    """Concrete AgentInterface that returns predictable responses for testing.

    Modes:
      blackbox  — output only
      greybox   — output + tool_calls + memory_reads + reasoning_steps
      trace     — output + agent_trace steps
      injection — echoes the first turn back (simulates echoing adversarial content)
    """

    async def invoke(self, payload: AttackPayload) -> AgentResponse:
        mode = _mode()
        first_turn = payload.turns[0] if payload.turns else ""

        if mode == "blackbox":
            return AgentResponse(
                output=f"[blackbox] received: {first_turn}",
                raw={"mode": "blackbox"},
            )

        if mode == "greybox":
            return AgentResponse(
                output=f"[greybox] processed: {first_turn}",
                tool_calls=[
                    ToolCallRecord(
                        tool="search",
                        args={"query": first_turn},
                        response={"results": []},
                    )
                ],
                memory_reads=[MemoryRecord(entry="test memory entry", score=0.9)],
                reasoning_steps=["Step 1: analyse input", "Step 2: call search tool"],
                raw={"mode": "greybox"},
            )

        if mode == "trace":
            return AgentResponse(
                output=f"[trace] executed: {first_turn}",
                agent_trace=[
                    AgentTraceStep(
                        step=1,
                        node="planner",
                        input=first_turn,
                        output="plan: call search",
                        latency_ms=210,
                    ),
                    AgentTraceStep(
                        step=2,
                        node="executor",
                        input="plan: call search",
                        output=f"[trace] executed: {first_turn}",
                        latency_ms=85,
                    ),
                ],
                raw={"mode": "trace"},
            )

        # injection mode — echo the payload back (simulates agent trusting tool output)
        return AgentResponse(
            output=first_turn,
            raw={"mode": "injection"},
        )

    async def stream(self, payload: AttackPayload) -> AsyncIterator[AgentEvent]:
        response = await self.invoke(payload)
        yield AgentEvent(event_type="token", data={"text": response.output})
        yield AgentEvent(event_type="done", data={"output": response.output})

    async def get_state(self) -> dict:
        return {"mode": _mode(), "status": "idle"}

    async def reset(self) -> None:
        pass  # stateless; reset is a no-op

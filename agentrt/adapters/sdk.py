from __future__ import annotations

from typing import AsyncIterator, Callable, Optional

from pydantic import BaseModel

from agentrt.adapters.base import (
    AgentEvent,
    AgentInterface,
    AgentResponse,
    AttackPayload,
)


class LangGraphHooks(BaseModel):
    """Node-level callbacks for LangGraph grey-box visibility.

    Scaffold only in Phase 1 — not wired to any graph in this phase.
    LangGraph hook plumbing is added in Phase 3 (orchestrator).
    """

    on_node_enter: Optional[Callable] = None
    on_node_exit: Optional[Callable] = None

    model_config = {"arbitrary_types_allowed": True}


class SDKAdapter(AgentInterface):
    """Calls the target agent as an in-process Python async callable.

    agent_callable  — any async callable that accepts AttackPayload and
                      returns AgentResponse.  When a bound method is passed
                      (e.g. agent.invoke), __self__ is inspected so that
                      reset() and get_state() can delegate to the same object
                      if it implements those methods.

    hooks           — optional LangGraphHooks; scaffolded here, wired in
                      Phase 3.
    """

    def __init__(
        self,
        agent_callable: Callable,
        hooks: LangGraphHooks | None = None,
    ) -> None:
        self._callable = agent_callable
        self._hooks = hooks
        # If a bound method is supplied, keep a reference to the owner so
        # reset() / get_state() can delegate without extra constructor args.
        self._owner = getattr(agent_callable, "__self__", None)

    # ------------------------------------------------------------------
    # AgentInterface implementation
    # ------------------------------------------------------------------

    async def invoke(self, payload: AttackPayload) -> AgentResponse:
        return await self._callable(payload)

    async def stream(self, payload: AttackPayload) -> AsyncIterator[AgentEvent]:
        # Check if the owner exposes a native stream method; fall back to
        # wrapping invoke in two events (token + done).
        if self._owner is not None and hasattr(self._owner, "stream"):
            async for event in self._owner.stream(payload):
                yield event
            return

        response = await self.invoke(payload)
        yield AgentEvent(event_type="token", data={"text": response.output})
        yield AgentEvent(event_type="done", data={"output": response.output})

    async def get_state(self) -> dict:
        if self._owner is not None and hasattr(self._owner, "get_state"):
            return await self._owner.get_state()
        return {}

    async def reset(self) -> None:
        if self._owner is not None and hasattr(self._owner, "reset"):
            await self._owner.reset()

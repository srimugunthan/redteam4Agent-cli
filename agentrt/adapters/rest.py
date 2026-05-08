from __future__ import annotations

from typing import AsyncIterator
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from agentrt.adapters.base import (
    AgentEvent,
    AgentInterface,
    AgentResponse,
    AttackPayload,
)


class RestAdapter(AgentInterface):
    """Calls the target agent over HTTP.

    endpoint  — the full invoke URL, e.g. http://localhost:9000/invoke.
                reset() and get_state() are derived by sibling-path resolution
                (same scheme://host:port, paths /reset and /state).

    The agent must return JSON matching the AgentResponse schema.  The
    optional instrumented fields (tool_calls, memory_reads, reasoning_steps,
    agent_trace) are populated when the agent opts into the transparency
    contract (§4.3 of system-design).

    reset()     — POSTs to /reset; 404 is silently ignored.
    get_state() — GETs /state; returns {} on any error or non-200 status.
    stream()    — calls /invoke and wraps the result in token + done events
                  (HTTP streaming is not required in Phase 1).
    """

    def __init__(self, endpoint: str, timeout: float = 30.0) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        # Derive the server root (scheme://host:port) for reset/state paths.
        parts = urlsplit(self._endpoint)
        self._root = urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    # ------------------------------------------------------------------
    # AgentInterface implementation
    # ------------------------------------------------------------------

    async def invoke(self, payload: AttackPayload) -> AgentResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                self._endpoint,
                content=payload.model_dump_json(),
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            return AgentResponse.model_validate(r.json())

    async def stream(self, payload: AttackPayload) -> AsyncIterator[AgentEvent]:
        response = await self.invoke(payload)
        yield AgentEvent(event_type="token", data={"text": response.output})
        yield AgentEvent(event_type="done", data={"output": response.output})

    async def get_state(self) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.get(f"{self._root}/state")
                if r.status_code == 200:
                    return r.json()
            except httpx.HTTPError:
                pass
        return {}

    async def reset(self) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                r = await client.post(f"{self._root}/reset")
                if r.status_code not in (200, 204, 404):
                    r.raise_for_status()
            except httpx.HTTPError:
                pass

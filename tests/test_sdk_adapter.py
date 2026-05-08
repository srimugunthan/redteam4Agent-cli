"""Phase 1B tests — SDKAdapter calling TestAgent in-process."""

from __future__ import annotations

import pytest

from agentrt.adapters.base import AttackPayload, AgentResponse
from agentrt.adapters.sdk import SDKAdapter, LangGraphHooks
from tests.test_agent.agent import TestAgent


# ---------------------------------------------------------------------------
# invoke() — all four agent modes via bound method
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invoke_blackbox(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()
    adapter = SDKAdapter(agent.invoke)
    resp = await adapter.invoke(AttackPayload(turns=["hello"], expected_behavior="respond"))
    assert "blackbox" in resp.output


@pytest.mark.asyncio
async def test_invoke_greybox(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "greybox")
    agent = TestAgent()
    adapter = SDKAdapter(agent.invoke)
    resp = await adapter.invoke(AttackPayload(turns=["hello"], expected_behavior="respond"))
    assert resp.tool_calls != []
    assert resp.memory_reads != []


@pytest.mark.asyncio
async def test_invoke_trace(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "trace")
    agent = TestAgent()
    adapter = SDKAdapter(agent.invoke)
    resp = await adapter.invoke(AttackPayload(turns=["plan"], expected_behavior="respond"))
    assert len(resp.agent_trace) == 2


@pytest.mark.asyncio
async def test_invoke_injection(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "injection")
    agent = TestAgent()
    adapter = SDKAdapter(agent.invoke)
    evil = "ADVERSARIAL_PAYLOAD"
    resp = await adapter.invoke(AttackPayload(turns=[evil], expected_behavior="refuse"))
    assert resp.output == evil


# ---------------------------------------------------------------------------
# stream() — delegates to owner.stream when available
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_via_owner(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()
    adapter = SDKAdapter(agent.invoke)
    events = [e async for e in adapter.stream(
        AttackPayload(turns=["hi"], expected_behavior="respond")
    )]
    assert events[0].event_type == "token"
    assert events[-1].event_type == "done"


@pytest.mark.asyncio
async def test_stream_fallback_when_no_stream_method(monkeypatch):
    """Plain callable (not a bound method) falls back to invoke-based streaming."""
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()

    async def plain_callable(payload: AttackPayload) -> AgentResponse:
        return await agent.invoke(payload)

    adapter = SDKAdapter(plain_callable)
    events = [e async for e in adapter.stream(
        AttackPayload(turns=["hi"], expected_behavior="respond")
    )]
    assert events[0].event_type == "token"
    assert events[-1].event_type == "done"


# ---------------------------------------------------------------------------
# reset() — delegates to owner.reset when available
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_via_owner(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()
    adapter = SDKAdapter(agent.invoke)
    await adapter.reset()  # must not raise


@pytest.mark.asyncio
async def test_reset_noop_for_plain_callable(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()

    async def plain_callable(payload: AttackPayload) -> AgentResponse:
        return await agent.invoke(payload)

    adapter = SDKAdapter(plain_callable)
    await adapter.reset()  # must not raise


# ---------------------------------------------------------------------------
# get_state() — delegates to owner.get_state when available
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_state_via_owner(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()
    adapter = SDKAdapter(agent.invoke)
    state = await adapter.get_state()
    assert state.get("status") == "idle"


@pytest.mark.asyncio
async def test_get_state_returns_empty_for_plain_callable(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()

    async def plain_callable(payload: AttackPayload) -> AgentResponse:
        return await agent.invoke(payload)

    adapter = SDKAdapter(plain_callable)
    state = await adapter.get_state()
    assert state == {}


# ---------------------------------------------------------------------------
# LangGraphHooks — scaffold: instantiates correctly, stored on adapter
# ---------------------------------------------------------------------------

def test_langgraph_hooks_scaffold():
    hooks = LangGraphHooks()
    assert hooks.on_node_enter is None
    assert hooks.on_node_exit is None


def test_langgraph_hooks_with_callbacks():
    entered = []
    exited = []

    def on_enter(node): entered.append(node)
    def on_exit(node): exited.append(node)

    hooks = LangGraphHooks(on_node_enter=on_enter, on_node_exit=on_exit)
    assert hooks.on_node_enter is on_enter
    assert hooks.on_node_exit is on_exit


@pytest.mark.asyncio
async def test_adapter_accepts_hooks(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_MODE", "blackbox")
    agent = TestAgent()
    hooks = LangGraphHooks()
    adapter = SDKAdapter(agent.invoke, hooks=hooks)
    resp = await adapter.invoke(AttackPayload(turns=["hi"], expected_behavior="respond"))
    assert resp.output  # hooks scaffolded but not wired in Phase 1

"""Tests for Category A — Prompt Injection & Goal Hijacking attack plugins."""

from __future__ import annotations

import os

import pytest

from agentrt.adapters.sdk import SDKAdapter
from agentrt.attacks.base import AttackContext
from agentrt.attacks.registry import PluginRegistry
from agentrt.config.settings import CampaignConfig
from tests.test_agent.agent import TestAgent


@pytest.fixture(autouse=True)
def register_category_a():
    """Reload category_a each test to re-fire @attack decorators."""
    import importlib
    import agentrt.attacks.category_a
    PluginRegistry.clear()
    importlib.reload(agentrt.attacks.category_a)
    yield
    PluginRegistry.clear()


def make_context():
    return AttackContext(run_id="test", config=CampaignConfig(name="test"))


# ---------------------------------------------------------------------------
# A-01
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a01_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("A-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "A-01"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
async def test_a01_injection_mode():
    """In injection mode TestAgent echoes back; success keywords may match."""
    os.environ["TEST_AGENT_MODE"] = "injection"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("A-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.turns[0] in result.response.output


@pytest.mark.asyncio
async def test_a01_payload_has_expected_behavior():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("A-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.expected_behavior == "refuse"


# ---------------------------------------------------------------------------
# A-02
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a02_requires_mock_server():
    """A-02 raises RuntimeError when no mock server in context."""
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("A-02")()
    ctx = make_context()  # mock_server=None
    with pytest.raises(RuntimeError, match="requires a MockToolServer"):
        await plugin.execute(agent, ctx)


# ---------------------------------------------------------------------------
# A-03, A-04, A-05
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["A-03", "A-04", "A-05"])
async def test_category_a_plugins_register_and_execute(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == plugin_id
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["A-03", "A-04", "A-05"])
async def test_category_a_plugins_payload_expected_behavior(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.expected_behavior == "refuse"


# ---------------------------------------------------------------------------
# All IDs registered
# ---------------------------------------------------------------------------

def test_all_category_a_ids_registered():
    registered_ids = {cls.id for cls in PluginRegistry.list_all()}
    for expected_id in ["A-01", "A-02", "A-03", "A-04", "A-05"]:
        assert expected_id in registered_ids, f"{expected_id} not registered"


# ---------------------------------------------------------------------------
# Injection mode echoes for non-mock-required plugins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["A-03", "A-04", "A-05"])
async def test_category_a_injection_mode_echoes(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "injection"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.turns[0] in result.response.output

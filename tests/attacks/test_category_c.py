"""Tests for Category C — Memory & State Attacks plugins."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from agentrt.adapters.sdk import SDKAdapter
from agentrt.attacks.base import AttackContext
from agentrt.attacks.registry import PluginRegistry
from agentrt.config.settings import CampaignConfig
from tests.test_agent.agent import TestAgent


@pytest.fixture(autouse=True)
def register_category_c():
    """Reload category_c each test to re-fire @attack decorators."""
    import importlib
    import agentrt.attacks.category_c
    PluginRegistry.clear()
    importlib.reload(agentrt.attacks.category_c)
    yield
    PluginRegistry.clear()


def make_context():
    return AttackContext(run_id="test", config=CampaignConfig(name="test"))


# ---------------------------------------------------------------------------
# C-01 (multi-session)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c01_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("C-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "C-01"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
async def test_c01_execute_calls_reset():
    """C-01 must call agent.reset() between sessions."""
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    test_agent = TestAgent()
    reset_mock = AsyncMock()
    test_agent.reset = reset_mock
    agent = SDKAdapter(test_agent.invoke)
    # Patch reset on the SDKAdapter's owner
    agent._owner = test_agent
    plugin = PluginRegistry.get("C-01")()
    await plugin.execute(agent, make_context())
    reset_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_c01_payload_expected_behavior():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("C-01")()
    result = await plugin.execute(agent, make_context())
    # The probe (session 2) payload should be "refuse"
    assert result.payload.expected_behavior == "refuse"


# ---------------------------------------------------------------------------
# C-02
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c02_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("C-02")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "C-02"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


# ---------------------------------------------------------------------------
# C-03
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c03_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("C-03")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "C-03"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


# ---------------------------------------------------------------------------
# C-04 (multi-session)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c04_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("C-04")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "C-04"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
async def test_c04_execute_calls_reset():
    """C-04 must call agent.reset() between sessions."""
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    test_agent = TestAgent()
    reset_mock = AsyncMock()
    test_agent.reset = reset_mock
    agent = SDKAdapter(test_agent.invoke)
    agent._owner = test_agent
    plugin = PluginRegistry.get("C-04")()
    await plugin.execute(agent, make_context())
    reset_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_c04_payload_expected_behavior():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("C-04")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.expected_behavior == "refuse"


# ---------------------------------------------------------------------------
# Parametrized across non-multi-session plugins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["C-02", "C-03"])
async def test_category_c_plugins_register_and_execute(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == plugin_id
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


# ---------------------------------------------------------------------------
# All IDs registered
# ---------------------------------------------------------------------------

def test_all_category_c_ids_registered():
    registered_ids = {cls.id for cls in PluginRegistry.list_all()}
    for expected_id in ["C-01", "C-02", "C-03", "C-04"]:
        assert expected_id in registered_ids, f"{expected_id} not registered"


# ---------------------------------------------------------------------------
# Injection mode echoes (single-turn plugins only)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["C-02", "C-03"])
async def test_category_c_injection_mode_echoes(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "injection"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.turns[0] in result.response.output

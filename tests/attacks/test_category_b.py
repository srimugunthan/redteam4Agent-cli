"""Tests for Category B — Tool Misuse & Abuse attack plugins."""

from __future__ import annotations

import os

import pytest

from agentrt.adapters.sdk import SDKAdapter
from agentrt.attacks.base import AttackContext
from agentrt.attacks.registry import PluginRegistry
from agentrt.config.settings import CampaignConfig
from tests.test_agent.agent import TestAgent


@pytest.fixture(autouse=True)
def register_category_b():
    """Reload category_b each test to re-fire @attack decorators."""
    import importlib
    import agentrt.attacks.category_b
    PluginRegistry.clear()
    importlib.reload(agentrt.attacks.category_b)
    yield
    PluginRegistry.clear()


def make_context():
    return AttackContext(run_id="test", config=CampaignConfig(name="test"))


# ---------------------------------------------------------------------------
# B-01
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b01_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("B-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "B-01"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
async def test_b01_payload_has_expected_behavior():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("B-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.expected_behavior == "refuse"


# ---------------------------------------------------------------------------
# B-02
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b02_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("B-02")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "B-02"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


# ---------------------------------------------------------------------------
# B-03
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b03_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("B-03")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "B-03"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


# ---------------------------------------------------------------------------
# B-04
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b04_requires_mock_server():
    """B-04 raises RuntimeError when no mock server in context."""
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("B-04")()
    ctx = make_context()  # mock_server=None
    with pytest.raises(RuntimeError, match="requires a MockToolServer"):
        await plugin.execute(agent, ctx)


# ---------------------------------------------------------------------------
# B-05
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b05_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("B-05")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "B-05"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


# ---------------------------------------------------------------------------
# Parametrized across non-mock-required plugins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["B-01", "B-02", "B-03", "B-05"])
async def test_category_b_plugins_register_and_execute(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == plugin_id
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["B-01", "B-02", "B-03", "B-05"])
async def test_category_b_plugins_payload_expected_behavior(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.expected_behavior == "refuse"


# ---------------------------------------------------------------------------
# All IDs registered
# ---------------------------------------------------------------------------

def test_all_category_b_ids_registered():
    registered_ids = {cls.id for cls in PluginRegistry.list_all()}
    for expected_id in ["B-01", "B-02", "B-03", "B-04", "B-05"]:
        assert expected_id in registered_ids, f"{expected_id} not registered"


# ---------------------------------------------------------------------------
# Injection mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["B-01", "B-02", "B-03", "B-05"])
async def test_category_b_injection_mode_echoes(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "injection"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.turns[0] in result.response.output

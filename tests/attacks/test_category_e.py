"""Tests for Category E — Reasoning & Planning Attacks plugins."""

from __future__ import annotations

import os

import pytest

from agentrt.adapters.sdk import SDKAdapter
from agentrt.attacks.base import AttackContext
from agentrt.attacks.registry import PluginRegistry
from agentrt.config.settings import CampaignConfig
from tests.test_agent.agent import TestAgent


@pytest.fixture(autouse=True)
def register_category_e():
    """Reload category_e each test to re-fire @attack decorators."""
    import importlib
    import agentrt.attacks.category_e
    PluginRegistry.clear()
    importlib.reload(agentrt.attacks.category_e)
    yield
    PluginRegistry.clear()


def make_context():
    return AttackContext(run_id="test", config=CampaignConfig(name="test"))


# ---------------------------------------------------------------------------
# E-01
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e01_execute_returns_result():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("E-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == "E-01"
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
async def test_e01_payload_has_expected_behavior():
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("E-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.expected_behavior == "refuse"


@pytest.mark.asyncio
async def test_e01_injection_mode():
    os.environ["TEST_AGENT_MODE"] = "injection"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get("E-01")()
    result = await plugin.execute(agent, make_context())
    assert result.payload.turns[0] in result.response.output


# ---------------------------------------------------------------------------
# Parametrized across all E-category plugins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["E-01", "E-02", "E-03", "E-04"])
async def test_category_e_plugins_register_and_execute(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.metadata["plugin_id"] == plugin_id
    assert result.response.output != ""
    assert result.verdict.success in (True, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["E-01", "E-02", "E-03", "E-04"])
async def test_category_e_plugins_payload_expected_behavior(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "blackbox"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.expected_behavior == "refuse"


# ---------------------------------------------------------------------------
# All IDs registered
# ---------------------------------------------------------------------------

def test_all_category_e_ids_registered():
    registered_ids = {cls.id for cls in PluginRegistry.list_all()}
    for expected_id in ["E-01", "E-02", "E-03", "E-04"]:
        assert expected_id in registered_ids, f"{expected_id} not registered"


# ---------------------------------------------------------------------------
# Injection mode echoes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["E-02", "E-03", "E-04"])
async def test_category_e_injection_mode_echoes(plugin_id):
    os.environ["TEST_AGENT_MODE"] = "injection"
    agent = SDKAdapter(TestAgent().invoke)
    plugin = PluginRegistry.get(plugin_id)()
    result = await plugin.execute(agent, make_context())
    assert result.payload.turns[0] in result.response.output

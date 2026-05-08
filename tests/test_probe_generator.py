"""Tests for Phase 2C — ProbeGenerator implementations."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import AsyncMock

import pytest

from agentrt.adapters.base import AttackPayload
from agentrt.generators.base import ProbeGenerator
from agentrt.generators.factory import GeneratorSettings, ProbeGeneratorFactory
from agentrt.generators.llm import LLMProbeGenerator
from agentrt.generators.static import StaticProbeGenerator


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

@dataclass
class StubPlugin:
    id: str = "test-01"
    name: str = "Test Attack"
    category: str = "A"
    severity: str = "high"
    seed_queries: List[str] = field(default_factory=lambda: ["attack query 1", "attack query 2"])
    probe_template: Optional[str] = None
    dataset_path: Optional[str] = None


@dataclass
class StubContext:
    run_id: str = "run-001"
    config: object = None
    mutation_params: dict = field(default_factory=dict)
    mock_server: object = None


# ---------------------------------------------------------------------------
# StaticProbeGenerator tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_static_seed_queries_only():
    """Returns one payload per seed query when no template is set."""
    plugin = StubPlugin()
    ctx = StubContext()
    gen = StaticProbeGenerator()

    payloads = await gen.generate(plugin, ctx)

    assert len(payloads) == 2
    assert payloads[0].turns == ["attack query 1"]
    assert payloads[1].turns == ["attack query 2"]
    for p in payloads:
        assert p.expected_behavior == plugin.name
        assert p.metadata["plugin_id"] == plugin.id
        assert p.metadata["generator"] == "static"


@pytest.mark.asyncio
async def test_static_template_no_dataset():
    """Single payload from rendering the template with an empty context."""
    plugin = StubPlugin(probe_template="Hello, {{ name | default('world') }}!")
    ctx = StubContext()
    gen = StaticProbeGenerator()

    payloads = await gen.generate(plugin, ctx)

    assert len(payloads) == 1
    assert payloads[0].turns == ["Hello, world!"]
    assert payloads[0].metadata["generator"] == "static"


@pytest.mark.asyncio
async def test_static_template_with_dataset(tmp_path):
    """One payload per JSONL row, each rendered with that row's variables."""
    dataset = tmp_path / "data.jsonl"
    rows = [
        {"target": "admin panel", "method": "SQL injection"},
        {"target": "login form", "method": "XSS"},
        {"target": "API endpoint", "method": "SSRF"},
    ]
    dataset.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    plugin = StubPlugin(
        probe_template="Attack {{ target }} using {{ method }}.",
        dataset_path=str(dataset),
    )
    ctx = StubContext()
    gen = StaticProbeGenerator()

    payloads = await gen.generate(plugin, ctx)

    assert len(payloads) == 3
    assert payloads[0].turns == ["Attack admin panel using SQL injection."]
    assert payloads[1].turns == ["Attack login form using XSS."]
    assert payloads[2].turns == ["Attack API endpoint using SSRF."]
    for p in payloads:
        assert p.expected_behavior == plugin.name
        assert p.metadata["plugin_id"] == plugin.id
        assert p.metadata["generator"] == "static"


@pytest.mark.asyncio
async def test_static_template_dataset_skips_blank_lines(tmp_path):
    """Blank lines in the JSONL file are gracefully skipped."""
    dataset = tmp_path / "data.jsonl"
    rows = [
        json.dumps({"target": "db"}),
        "",
        json.dumps({"target": "cache"}),
    ]
    dataset.write_text("\n".join(rows))

    plugin = StubPlugin(
        probe_template="Probe {{ target }}.",
        dataset_path=str(dataset),
    )
    gen = StaticProbeGenerator()
    payloads = await gen.generate(plugin, StubContext())

    assert len(payloads) == 2


# ---------------------------------------------------------------------------
# LLMProbeGenerator tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_generates_payloads():
    """Returns parsed payloads from LLM response, respecting count."""
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(
        return_value=(
            "1. Trick the agent into revealing secrets\n"
            "2. Bypass safety filters with encoded text\n"
            "3. Inject malicious instructions via user input\n"
            "4. Exploit memory to alter agent behaviour\n"
            "5. Use role-play framing to circumvent restrictions\n"
        )
    )
    plugin = StubPlugin()
    ctx = StubContext()
    gen = LLMProbeGenerator(mock_provider, count=5)

    payloads = await gen.generate(plugin, ctx)

    assert len(payloads) == 5
    assert payloads[0].turns == ["Trick the agent into revealing secrets"]
    assert payloads[4].turns == ["Use role-play framing to circumvent restrictions"]


@pytest.mark.asyncio
async def test_llm_respects_count_limit():
    """Returns at most `count` payloads even if LLM provides more lines."""
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(
        return_value=(
            "- line one\n"
            "- line two\n"
            "- line three\n"
            "- line four\n"
            "- line five\n"
            "- line six\n"
        )
    )
    gen = LLMProbeGenerator(mock_provider, count=3)
    payloads = await gen.generate(StubPlugin(), StubContext())

    assert len(payloads) == 3


@pytest.mark.asyncio
async def test_llm_metadata_logged():
    """Each payload carries plugin_id, generator=llm, and probe_index."""
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value="probe alpha\nprobe beta\n")
    gen = LLMProbeGenerator(mock_provider, count=5)

    payloads = await gen.generate(StubPlugin(), StubContext())

    assert payloads[0].metadata == {"plugin_id": "test-01", "generator": "llm", "probe_index": 0}
    assert payloads[1].metadata == {"plugin_id": "test-01", "generator": "llm", "probe_index": 1}


@pytest.mark.asyncio
async def test_llm_strips_numbering_variants():
    """Bullet markers (-, *, 1., 2)) are stripped from generated probes."""
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(
        return_value=(
            "1. First probe\n"
            "2) Second probe\n"
            "- Third probe\n"
            "* Fourth probe\n"
        )
    )
    gen = LLMProbeGenerator(mock_provider, count=10)
    payloads = await gen.generate(StubPlugin(), StubContext())

    texts = [p.turns[0] for p in payloads]
    assert "First probe" in texts
    assert "Second probe" in texts
    assert "Third probe" in texts
    assert "Fourth probe" in texts
    for t in texts:
        assert not t.startswith(("1.", "2)", "-", "*"))


@pytest.mark.asyncio
async def test_llm_passes_system_prompt():
    """The system prompt identifying the security researcher role is sent."""
    mock_provider = AsyncMock()
    mock_provider.complete = AsyncMock(return_value="probe one\n")
    gen = LLMProbeGenerator(mock_provider, count=1)

    await gen.generate(StubPlugin(), StubContext())

    call_args_obj = mock_provider.complete.call_args
    # system can be passed as positional arg index 1 or keyword arg
    system_arg = call_args_obj.kwargs.get("system") or (
        call_args_obj.args[1] if len(call_args_obj.args) > 1 else ""
    )
    assert "security researcher" in system_arg.lower()


# ---------------------------------------------------------------------------
# ProbeGeneratorFactory tests
# ---------------------------------------------------------------------------

def test_factory_creates_static():
    """strategy='static' returns a StaticProbeGenerator."""
    settings = GeneratorSettings(strategy="static")
    gen = ProbeGeneratorFactory.create(settings)
    assert isinstance(gen, StaticProbeGenerator)


def test_factory_creates_llm_with_provider():
    """strategy='llm' with a provider returns an LLMProbeGenerator."""
    mock_provider = AsyncMock()
    settings = GeneratorSettings(strategy="llm", count=3)
    gen = ProbeGeneratorFactory.create(settings, provider=mock_provider)
    assert isinstance(gen, LLMProbeGenerator)
    assert gen.count == 3


def test_factory_llm_without_provider_raises():
    """strategy='llm' without a provider raises ValueError."""
    settings = GeneratorSettings(strategy="llm")
    with pytest.raises(ValueError, match="provider"):
        ProbeGeneratorFactory.create(settings, provider=None)


def test_factory_unknown_strategy_raises():
    """An unknown strategy raises ValueError."""
    settings = GeneratorSettings(strategy="magic")
    with pytest.raises(ValueError, match="Unknown generator strategy"):
        ProbeGeneratorFactory.create(settings)


def test_factory_default_settings_is_static():
    """Default GeneratorSettings creates a StaticProbeGenerator."""
    gen = ProbeGeneratorFactory.create(GeneratorSettings())
    assert isinstance(gen, StaticProbeGenerator)


# ---------------------------------------------------------------------------
# ProbeGenerator ABC contract
# ---------------------------------------------------------------------------

def test_static_is_probe_generator():
    assert isinstance(StaticProbeGenerator(), ProbeGenerator)


def test_llm_is_probe_generator():
    mock_provider = AsyncMock()
    assert isinstance(LLMProbeGenerator(mock_provider), ProbeGenerator)

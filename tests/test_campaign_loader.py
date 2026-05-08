"""Tests for Phase 4B — Campaign Loader (agentrt/config/loader.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from agentrt.attacks.registry import PluginRegistry
from agentrt.config.loader import (
    load_campaign,
    resolve_adapter,
    resolve_plugins,
    resolve_search_strategy,
)
from agentrt.config.settings import CampaignConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_YAML = FIXTURES_DIR / "sample.yaml"


@pytest.fixture()
def sample_config() -> CampaignConfig:
    """Load the sample fixture into a CampaignConfig."""
    return load_campaign(SAMPLE_YAML)


@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure a clean plugin registry for each test to avoid duplicate-id errors.

    We clear *after* each test so the next test starts with an empty registry.
    We do NOT clear before (that would prevent discover() from working when the
    module is already cached in sys.modules and the @attack decorator won't fire
    a second time).
    """
    yield
    PluginRegistry.clear()


@pytest.fixture()
def populated_registry():
    """Ensure A-01-stub is registered (handles the case where the module is already
    cached in sys.modules and @attack won't fire on reimport)."""
    PluginRegistry.clear()
    # Re-register the stub directly when the module is already cached
    from agentrt.attacks.stubs import A01StubPlugin
    try:
        PluginRegistry.register(A01StubPlugin)
    except Exception:
        pass  # Already registered; that's fine
    yield
    PluginRegistry.clear()


# ---------------------------------------------------------------------------
# load_campaign tests
# ---------------------------------------------------------------------------

def test_load_campaign_basic(sample_config: CampaignConfig):
    assert sample_config.name == "Sample Red Team Campaign"
    assert sample_config.target.type == "rest"
    assert sample_config.attacks.categories == ["A"]


def test_load_campaign_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_campaign(Path("nonexistent.yaml"))


def test_load_campaign_invalid_yaml_raises(tmp_path: Path):
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("name: [unclosed", encoding="utf-8")
    with pytest.raises((yaml.YAMLError, Exception)):
        load_campaign(bad_yaml)


def test_load_campaign_with_overrides(sample_config: CampaignConfig):
    """CLI overrides should win over YAML values."""
    config = load_campaign(SAMPLE_YAML, overrides={"execution": {"mutation_count": 5}})
    assert config.execution.mutation_count == 5


def test_load_campaign_overrides_do_not_clobber_other_fields():
    """An override for one subkey should not destroy sibling keys."""
    config = load_campaign(SAMPLE_YAML, overrides={"execution": {"mutation_count": 3}})
    # mode was set to sequential in the YAML; make sure it survived
    assert config.execution.mode == "sequential"
    assert config.execution.mutation_count == 3


# ---------------------------------------------------------------------------
# resolve_adapter tests
# ---------------------------------------------------------------------------

def test_resolve_adapter_rest(sample_config: CampaignConfig):
    from agentrt.adapters.rest import RestAdapter

    adapter = resolve_adapter(sample_config)
    assert isinstance(adapter, RestAdapter)


def test_resolve_adapter_unknown_raises():
    config = CampaignConfig.model_validate(
        {
            "name": "grpc-test",
            "target": {"type": "grpc", "endpoint": "http://localhost:50051"},
        }
    )
    with pytest.raises(ValueError, match="Unknown target type"):
        resolve_adapter(config)


def test_resolve_adapter_sdk_raises():
    config = CampaignConfig.model_validate(
        {
            "name": "sdk-test",
            "target": {"type": "sdk"},
        }
    )
    with pytest.raises(ValueError, match="SDK adapter requires"):
        resolve_adapter(config)


# ---------------------------------------------------------------------------
# resolve_plugins tests
# ---------------------------------------------------------------------------

def _make_config_with_categories(categories: list) -> CampaignConfig:
    return CampaignConfig.model_validate(
        {
            "name": "plugin-test",
            "target": {"type": "rest", "endpoint": "http://localhost:9000/invoke"},
            "attacks": {"categories": categories},
        }
    )


def test_resolve_plugins_empty_categories_returns_all(populated_registry):
    """Empty categories list should return every registered plugin."""
    config = _make_config_with_categories([])
    plugins = resolve_plugins(config)
    ids = {p.id for p in plugins}
    # A-01-stub is discovered via entry-point / module walk
    assert "A-01-stub" in ids


def test_resolve_plugins_category_filter(populated_registry):
    """Filtering by category letter 'A' should return only A-category plugins."""
    config = _make_config_with_categories(["A"])
    plugins = resolve_plugins(config)
    assert all(p.category == "A" for p in plugins)
    assert len(plugins) >= 1


def test_resolve_plugins_specific_id(populated_registry):
    """Filtering by full plugin id 'A-01-stub' should return exactly that plugin."""
    config = _make_config_with_categories(["A-01-stub"])
    plugins = resolve_plugins(config)
    assert len(plugins) == 1
    assert plugins[0].id == "A-01-stub"


def test_resolve_plugins_nonexistent_category_returns_empty(populated_registry):
    """Filtering by a category that has no plugins should return empty list."""
    config = _make_config_with_categories(["Z"])
    plugins = resolve_plugins(config)
    assert plugins == []


# ---------------------------------------------------------------------------
# resolve_search_strategy tests
# ---------------------------------------------------------------------------

def _make_config_with_strategy(strategy: str, count: int) -> CampaignConfig:
    return CampaignConfig.model_validate(
        {
            "name": "strategy-test",
            "target": {"type": "rest", "endpoint": "http://localhost:9000/invoke"},
            "execution": {
                "mutation_strategy": strategy,
                "mutation_count": count,
            },
        }
    )


def test_resolve_search_strategy_static():
    from agentrt.engine.mutation import StaticStrategy

    config = _make_config_with_strategy("static", 3)
    strategy = resolve_search_strategy(config)
    assert isinstance(strategy, StaticStrategy)


def test_resolve_search_strategy_zero_count():
    """mutation_count=0 should return StaticStrategy regardless of strategy field."""
    from agentrt.engine.mutation import StaticStrategy

    config = _make_config_with_strategy("llm", 0)
    strategy = resolve_search_strategy(config)
    assert isinstance(strategy, StaticStrategy)


def test_resolve_search_strategy_unknown_falls_back_to_static():
    """Unknown strategy name falls back to StaticStrategy."""
    from agentrt.engine.mutation import StaticStrategy

    config = _make_config_with_strategy("nonexistent_strategy", 5)
    strategy = resolve_search_strategy(config)
    assert isinstance(strategy, StaticStrategy)


# ---------------------------------------------------------------------------
# Profile-merging test
# ---------------------------------------------------------------------------

def test_load_campaign_profile_merging(tmp_path: Path):
    """A campaign YAML with 'profile: quick' should merge profile defaults.

    The 'quick' built-in profile sets attacks.categories to specific IDs.
    If the campaign YAML overrides categories, the YAML value wins.
    If the campaign YAML omits them, the profile defaults survive.
    """
    # Campaign that references the built-in 'quick' profile but overrides categories
    campaign_yaml = tmp_path / "campaign.yaml"
    campaign_yaml.write_text(
        textwrap.dedent(
            """\
            name: "Profile Test Campaign"
            version: "1.0"
            profile: quick
            target:
              type: rest
              endpoint: http://localhost:9000/invoke
            attacks:
              categories:
                - A
                - B
            """
        ),
        encoding="utf-8",
    )
    config = load_campaign(campaign_yaml)
    # The YAML-level categories should win over profile defaults
    assert config.attacks.categories == ["A", "B"]
    # Profile sets judge model to claude-haiku-...; YAML doesn't override it,
    # so profile default should survive
    assert "haiku" in config.judge.model.lower()


def test_load_campaign_profile_defaults_survive_without_override(tmp_path: Path):
    """When the campaign YAML doesn't set judge.model, the profile default applies."""
    campaign_yaml = tmp_path / "campaign.yaml"
    campaign_yaml.write_text(
        textwrap.dedent(
            """\
            name: "Profile Defaults Test"
            profile: quick
            target:
              type: rest
              endpoint: http://localhost:9000/invoke
            """
        ),
        encoding="utf-8",
    )
    config = load_campaign(campaign_yaml)
    # 'quick' profile sets mutation_count: 0 and mutation_strategy: static
    assert config.execution.mutation_count == 0
    assert config.execution.mutation_strategy == "static"

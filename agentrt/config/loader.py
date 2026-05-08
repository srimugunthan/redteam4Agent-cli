"""Campaign loader for AgentRedTeam — Phase 4B.

Provides:
- load_campaign: read + validate a campaign YAML into CampaignConfig
- resolve_adapter: instantiate the correct AgentInterface from config
- resolve_judge: build the configured JudgeEngine
- resolve_probe_generator: build the configured ProbeGenerator
- resolve_plugins: filter PluginRegistry by configured attack categories
- resolve_search_strategy: select the mutation SearchStrategy
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from agentrt.config.settings import (
    AgentrtSettings,
    CampaignConfig,
    ProfileLoader,
    ProfileNotFoundError,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*; override wins on conflicts."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_campaign(path: Path, overrides: dict | None = None) -> CampaignConfig:
    """Load and validate a campaign YAML file.

    1. Read YAML from *path*.
    2. If config has a ``profile`` key, load that profile via ProfileLoader
       and use it as a defaults layer.
    3. Merge: profile defaults < YAML values < overrides.
    4. Validate into CampaignConfig.
    5. Return populated CampaignConfig.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    yaml.YAMLError
        If the file contains malformed YAML.
    pydantic.ValidationError
        If the merged dict fails Pydantic validation.
    ProfileNotFoundError
        If the campaign specifies a profile that cannot be found.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Campaign file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if raw is None:
        raw = {}

    # Layer 1: profile defaults (if any)
    profile_name = raw.get("profile")
    merged: dict = {}
    if profile_name:
        profile_data = ProfileLoader.load(profile_name)
        merged = _deep_merge(merged, profile_data)

    # Layer 2: YAML values
    merged = _deep_merge(merged, raw)

    # Layer 3: CLI overrides
    if overrides:
        merged = _deep_merge(merged, overrides)

    return CampaignConfig.model_validate(merged)


def resolve_adapter(config: CampaignConfig):
    """Instantiate the correct adapter from *config.target*.

    - ``type == "rest"``: return ``RestAdapter(config.target.endpoint)``
    - ``type == "sdk"``:  raise ``ValueError``
    - unknown:            raise ``ValueError``
    """
    from agentrt.adapters.rest import RestAdapter

    target_type = config.target.type
    if target_type == "rest":
        return RestAdapter(config.target.endpoint or "")
    if target_type == "sdk":
        raise ValueError(
            "SDK adapter requires an agent_callable; use SDKAdapter directly"
        )
    raise ValueError(f"Unknown target type: {target_type!r}")


def resolve_judge(
    config: CampaignConfig,
    api_keys: Optional[AgentrtSettings] = None,
):
    """Build the configured judge engine.

    For ``provider == "keyword"``: returns ``KeywordJudge``.
    For ``provider == "schema"``:  returns ``SchemaJudge``.
    For all others:                creates an LLM provider and returns ``LLMJudge``.
    """
    from agentrt.judge.keyword import KeywordJudge
    from agentrt.judge.schema import SchemaJudge
    from agentrt.judge.llm import LLMJudge
    from agentrt.providers.factory import LLMProviderFactory

    provider_name = config.judge.provider

    if provider_name == "keyword":
        keywords = [
            c.get("value", "") for c in config.evaluation.criteria if "value" in c
        ]
        return KeywordJudge(keywords=keywords)

    if provider_name == "schema":
        schema: dict = {}
        for c in config.evaluation.criteria:
            if "schema" in c:
                schema = c["schema"]
                break
        return SchemaJudge(schema=schema)

    # LLM-backed judge
    if api_keys is None:
        api_keys = AgentrtSettings()

    kwargs: dict = {"temperature": config.judge.temperature}
    if provider_name == "anthropic" and api_keys.ANTHROPIC_API_KEY:
        kwargs["api_key"] = api_keys.ANTHROPIC_API_KEY
    elif provider_name == "openai" and api_keys.OPENAI_API_KEY:
        kwargs["api_key"] = api_keys.OPENAI_API_KEY

    provider_instance = LLMProviderFactory.create(
        provider_name,
        config.judge.model,
        **kwargs,
    )
    return LLMJudge(provider=provider_instance)


def resolve_probe_generator(
    config: CampaignConfig,
    api_keys: Optional[AgentrtSettings] = None,
):
    """Build the configured probe generator.

    - ``strategy == "static"``: return ``StaticProbeGenerator``
    - ``strategy == "llm"``:    create LLM provider and return ``LLMProbeGenerator``
    """
    from agentrt.generators.static import StaticProbeGenerator
    from agentrt.generators.llm import LLMProbeGenerator
    from agentrt.providers.factory import LLMProviderFactory

    strategy = config.generator.strategy

    if strategy == "static":
        return StaticProbeGenerator()

    # "llm" strategy
    if api_keys is None:
        api_keys = AgentrtSettings()

    kwargs: dict = {}
    provider_name = config.generator.provider
    if provider_name == "anthropic" and api_keys.ANTHROPIC_API_KEY:
        kwargs["api_key"] = api_keys.ANTHROPIC_API_KEY
    elif provider_name == "openai" and api_keys.OPENAI_API_KEY:
        kwargs["api_key"] = api_keys.OPENAI_API_KEY

    provider_instance = LLMProviderFactory.create(
        provider_name,
        config.generator.model,
        **kwargs,
    )
    return LLMProbeGenerator(provider=provider_instance, count=config.generator.count)


def resolve_plugins(config: CampaignConfig) -> list:
    """Filter PluginRegistry by *config.attacks.categories*.

    Calls ``PluginRegistry.discover()`` first to ensure all built-ins and
    entry-point plugins are loaded.

    - If ``categories`` is empty, all registered plugins are returned.
    - Otherwise a plugin matches when its category letter (e.g. ``"A"``) OR its
      full id (e.g. ``"A-01-stub"``) is present in ``categories``.

    Returns a list of *instances* (not classes).
    """
    from agentrt.attacks.registry import PluginRegistry

    PluginRegistry.discover()

    all_classes = PluginRegistry.list_all()

    categories = config.attacks.categories
    if not categories:
        return [cls() for cls in all_classes]

    filtered = []
    for cls in all_classes:
        # Match by category letter or full plugin id
        if cls.category in categories or cls.id in categories:
            filtered.append(cls())
    return filtered


def resolve_search_strategy(
    config: CampaignConfig,
    api_keys: Optional[AgentrtSettings] = None,
):
    """Select the mutation SearchStrategy.

    - ``mutation_strategy == "static"`` or ``mutation_count == 0``: StaticStrategy
    - ``"template"``: TemplateStrategy
    - ``"llm"``:      LLMStrategy
    """
    from agentrt.engine.mutation import StaticStrategy, TemplateStrategy, LLMStrategy
    from agentrt.providers.factory import LLMProviderFactory

    if config.execution.mutation_count == 0 or config.execution.mutation_strategy == "static":
        return StaticStrategy()

    if config.execution.mutation_strategy == "template":
        return TemplateStrategy(config.execution.mutation_transforms or None)

    if config.execution.mutation_strategy == "llm":
        if api_keys is None:
            api_keys = AgentrtSettings()
        provider_instance = LLMProviderFactory.create(
            config.judge.provider,   # reuse judge provider for mutation
            config.judge.model,
            api_key=getattr(api_keys, f"{config.judge.provider}_api_key", None),
        )
        return LLMStrategy(provider=provider_instance, count=config.execution.mutation_count)

    # Unknown strategy — default to static
    return StaticStrategy()

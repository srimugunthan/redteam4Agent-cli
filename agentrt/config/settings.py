"""Config management for AgentRedTeam — Phase 4A.

Provides:
- CampaignConfig: Pydantic model for campaign YAML files
- AgentrtSettings: pydantic-settings model for env var configuration
- ProfileLoader: loads named profiles from disk
- ProfileNotFoundError: raised when a profile cannot be found
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class ProfileNotFoundError(Exception):
    """Raised when a requested profile YAML cannot be found."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Profile '{name}' not found. "
                         f"Checked ~/.config/agentrt/profiles/{name}.yaml "
                         f"and the built-in package profiles.")


# ---------------------------------------------------------------------------
# Nested config models
# ---------------------------------------------------------------------------

class TargetConfig(BaseModel):
    type: str = "rest"
    endpoint: Optional[str] = None
    initial_state: dict = Field(default_factory=dict)


class JudgeConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    provider: str = "anthropic"
    temperature: float = 0.0


class GeneratorConfig(BaseModel):
    strategy: str = "static"
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    count: int = 3


class ExecutionConfig(BaseModel):
    mode: str = "sequential"
    max_turns: int = 10
    timeout_seconds: int = 120
    retry_on_failure: int = 2
    mutation_count: int = 0
    mutation_strategy: str = "static"
    mutation_transforms: List[str] = Field(
        default_factory=lambda: [
            "base64",
            "language_swap",
            "case_inversion",
            "unicode_confusables",
        ]
    )


class AttacksConfig(BaseModel):
    categories: List[str] = Field(default_factory=list)
    custom: List[dict] = Field(default_factory=list)


class EvaluationConfig(BaseModel):
    criteria: List[dict] = Field(default_factory=list)


class MockRouteConfig(BaseModel):
    path: str
    response: dict


class MockServerConfig(BaseModel):
    routes: List[MockRouteConfig] = Field(default_factory=list)


class ReportingConfig(BaseModel):
    formats: List[str] = Field(default_factory=lambda: ["json"])
    output_dir: str = "./reports/"
    include_traces: str = "failures"
    severity_threshold: str = "medium"


# ---------------------------------------------------------------------------
# Top-level campaign config
# ---------------------------------------------------------------------------

class CampaignConfig(BaseModel):
    name: str = "default"
    version: str = "1.0"
    profile: Optional[str] = None

    target: TargetConfig = Field(default_factory=TargetConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    generator: GeneratorConfig = Field(default_factory=GeneratorConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    attacks: AttacksConfig = Field(default_factory=AttacksConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    mock_server: MockServerConfig = Field(default_factory=MockServerConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)

    checkpoint_db_path: str = ".agentrt/checkpoints.db"


# ---------------------------------------------------------------------------
# Environment variable settings
# ---------------------------------------------------------------------------

class AgentrtSettings(BaseSettings):
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    AGENTRT_PROFILE: Optional[str] = None
    AGENTRT_JUDGE_MODEL: Optional[str] = None
    AGENTRT_JUDGE_PROVIDER: Optional[str] = None
    AGENTRT_CHECKPOINT_DB: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# ---------------------------------------------------------------------------
# Profile loader
# ---------------------------------------------------------------------------

# Package-relative profiles directory (alongside this file)
_BUILTIN_PROFILES_DIR = Path(__file__).parent / "profiles"


class ProfileLoader:
    """Loads named profiles from disk.

    Search order:
    1. ``~/.config/agentrt/profiles/<name>.yaml``  (user override)
    2. ``agentrt/config/profiles/<name>.yaml``      (built-in, package-relative)

    Raises ``ProfileNotFoundError`` if neither location has the file.
    """

    @staticmethod
    def load(name: str) -> dict:
        """Return the raw profile dict for *name*.

        Parameters
        ----------
        name:
            Profile name without the ``.yaml`` extension.

        Returns
        -------
        dict
            Parsed YAML content of the profile file.

        Raises
        ------
        ProfileNotFoundError
            If no matching profile file is found.
        """
        filename = f"{name}.yaml"

        # 1. User override path
        user_path = Path.home() / ".config" / "agentrt" / "profiles" / filename
        if user_path.exists():
            with user_path.open("r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}

        # 2. Built-in (package-relative) path
        builtin_path = _BUILTIN_PROFILES_DIR / filename
        if builtin_path.exists():
            with builtin_path.open("r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}

        raise ProfileNotFoundError(name)

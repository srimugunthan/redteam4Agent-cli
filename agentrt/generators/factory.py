from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from agentrt.generators.base import ProbeGenerator
from agentrt.generators.llm import LLMProvider, LLMProbeGenerator
from agentrt.generators.static import StaticProbeGenerator


@dataclass
class GeneratorSettings:
    strategy: str = "static"   # "static" | "llm"
    count: int = 5


class ProbeGeneratorFactory:
    @staticmethod
    def create(
        settings: GeneratorSettings,
        provider: Optional[LLMProvider] = None,
    ) -> ProbeGenerator:
        if settings.strategy == "static":
            return StaticProbeGenerator()
        if settings.strategy == "llm":
            if provider is None:
                raise ValueError("LLMProbeGenerator requires a provider")
            return LLMProbeGenerator(provider, count=settings.count)
        raise ValueError(f"Unknown generator strategy: {settings.strategy!r}")

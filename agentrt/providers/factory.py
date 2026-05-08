"""Factory for creating LLM provider instances."""

from __future__ import annotations

from agentrt.providers.base import LLMProvider
from agentrt.providers.anthropic import AnthropicProvider
from agentrt.providers.openai import OpenAIProvider
from agentrt.providers.ollama import OllamaProvider


class LLMProviderFactory:
    @staticmethod
    def create(provider: str, model: str, **kwargs) -> LLMProvider:
        """Instantiate and return the requested LLM provider.

        Args:
            provider: One of ``"anthropic"``, ``"openai"``, or ``"ollama"``.
            model: The model identifier string.
            **kwargs: Provider-specific keyword arguments (e.g. ``api_key``, ``temperature``).

        Raises:
            ValueError: If *provider* is not recognised.
        """
        if provider == "anthropic":
            return AnthropicProvider(model, **kwargs)
        if provider == "openai":
            return OpenAIProvider(model, **kwargs)
        if provider == "ollama":
            return OllamaProvider(model, **kwargs)
        raise ValueError(
            f"Unknown provider: {provider!r}. Choose from: anthropic, openai, ollama"
        )

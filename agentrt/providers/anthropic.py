"""Anthropic Claude provider implementation."""

from __future__ import annotations

import json


class AnthropicProvider:
    """LLM provider backed by the Anthropic API."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        # Lazy import so that test environments without the SDK still import this module
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required to use AnthropicProvider. "
                "Install it with: pip install anthropic"
            ) from exc

        self.model = model
        self.temperature = temperature

        import anthropic as _anthropic  # local alias for use in methods
        self._client = _anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, prompt: str, system: str = "") -> str:
        """Send a prompt and return the text response."""
        kwargs: dict = dict(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system

        response = await self._client.messages.create(**kwargs)
        return response.content[0].text

    async def complete_structured(self, prompt: str, schema: dict) -> dict:
        """Return a JSON-parsed response, falling back to ``{"raw": text}`` on failure."""
        json_prompt = (
            f"{prompt}\n\nRespond ONLY with valid JSON matching this schema: {json.dumps(schema)}"
        )
        text = await self.complete(json_prompt)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"raw": text}

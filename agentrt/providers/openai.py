"""OpenAI provider implementation."""

from __future__ import annotations

import json


class OpenAIProvider:
    """LLM provider backed by the OpenAI API."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required to use OpenAIProvider. "
                "Install it with: pip install openai"
            ) from exc

        self.model = model
        self.temperature = temperature

        import openai as _openai
        self._client = _openai.AsyncOpenAI(api_key=api_key)

    async def complete(self, prompt: str, system: str = "") -> str:
        """Send a prompt and return the text response."""
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=messages,
        )
        return response.choices[0].message.content

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

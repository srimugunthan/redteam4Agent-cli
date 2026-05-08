"""Ollama provider implementation (uses httpx, no extra dependency)."""

from __future__ import annotations

import json

import httpx


class OllamaProvider:
    """LLM provider backed by a local Ollama instance via its REST API."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def complete(self, prompt: str, system: str = "") -> str:
        """Send a prompt to Ollama and return the response text."""
        body: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            body["system"] = system

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=body,
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json()["response"]

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

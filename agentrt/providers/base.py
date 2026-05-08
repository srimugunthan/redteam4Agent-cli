from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(self, prompt: str, system: str = "") -> str: ...
    async def complete_structured(self, prompt: str, schema: dict) -> dict: ...

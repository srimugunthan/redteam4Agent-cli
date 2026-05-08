from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from agentrt.adapters.base import AgentResponse, JudgeVerdict


class JudgeEngine(ABC):
    @abstractmethod
    async def evaluate(
        self,
        responses: List[AgentResponse],
        expected_behavior: str,
    ) -> JudgeVerdict: ...

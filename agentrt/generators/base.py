from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

from agentrt.adapters.base import AttackPayload

if TYPE_CHECKING:
    from agentrt.attacks.base import AttackContext, AttackPlugin


class ProbeGenerator(ABC):
    @abstractmethod
    async def generate(
        self,
        plugin: "AttackPlugin",
        context: "AttackContext",
    ) -> List[AttackPayload]: ...

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from agentrt.adapters.base import AgentInterface, AttackResult
    from agentrt.config.settings import CampaignConfig
    from agentrt.mock_server.server import MockToolServer


@dataclass
class AttackContext:
    run_id: str
    config: "CampaignConfig"
    mutation_params: dict = field(default_factory=dict)
    mock_server: Optional["MockToolServer"] = None


class AttackPlugin(ABC):
    id: str
    name: str
    category: str       # A | B | C | E | F
    severity: str       # critical | high | medium | low
    seed_queries: List[str] = []
    probe_template: Optional[str] = None
    dataset_path: Optional[str] = None

    @abstractmethod
    async def execute(self, agent: "AgentInterface", context: AttackContext) -> "AttackResult": ...


def attack(*, id: str, name: str, category: str, severity: str):
    """Class decorator that stamps metadata and registers the plugin."""
    def decorator(cls: type[AttackPlugin]) -> type[AttackPlugin]:
        cls.id = id
        cls.name = name
        cls.category = category
        cls.severity = severity
        # Lazy import to avoid circular imports: registry imports from base for
        # AttackPlugin type annotation, so we defer the import to call time.
        from agentrt.attacks.registry import PluginRegistry
        PluginRegistry.register(cls)
        return cls
    return decorator

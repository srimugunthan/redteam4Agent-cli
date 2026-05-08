from __future__ import annotations

from typing import List, Optional, Tuple

from typing_extensions import TypedDict

# Import concrete types — LangGraph calls get_type_hints() on the TypedDict
# at graph construction time, so string forward references won't resolve.
from agentrt.adapters.base import AttackPayload, AgentResponse, JudgeVerdict


class AttackState(TypedDict):
    run_id: str
    plugin_queue: List[str]              # plugin IDs — instances live in AttackGraphConfig.plugins
    current_payload: Optional[AttackPayload]
    conversation_history: List[Tuple[str, AgentResponse]]
    responses: List[AgentResponse]
    verdict: Optional[JudgeVerdict]
    attack_queue: List[AttackPayload]
    mutation_count: int

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator, List, Optional

from pydantic import BaseModel


class ToolCallRecord(BaseModel):
    tool: str
    args: dict
    response: dict


class MemoryRecord(BaseModel):
    entry: str
    score: float


class AgentTraceStep(BaseModel):
    step: int
    node: str
    input: str
    output: str
    latency_ms: Optional[float] = None


class AgentEvent(BaseModel):
    event_type: str  # token | tool_call | state_change | done
    data: dict


class AttackPayload(BaseModel):
    turns: List[str]
    expected_behavior: str
    metadata: dict = {}


class AgentResponse(BaseModel):
    output: str
    tool_calls: List[ToolCallRecord] = []
    memory_reads: List[MemoryRecord] = []
    reasoning_steps: List[str] = []
    agent_trace: List[AgentTraceStep] = []
    raw: dict = {}


class JudgeVerdict(BaseModel):
    success: bool
    confidence: float
    explanation: str
    raw_response: str


class AttackResult(BaseModel):
    payload: AttackPayload
    response: AgentResponse
    verdict: JudgeVerdict


class CampaignResult(BaseModel):
    run_id: str
    campaign_name: str
    results: List[AttackResult]
    started_at: datetime
    completed_at: datetime


class AgentInterface(ABC):
    @abstractmethod
    async def invoke(self, payload: AttackPayload) -> AgentResponse: ...

    @abstractmethod
    async def stream(self, payload: AttackPayload) -> AsyncIterator[AgentEvent]: ...

    @abstractmethod
    async def get_state(self) -> dict: ...

    @abstractmethod
    async def reset(self) -> None: ...

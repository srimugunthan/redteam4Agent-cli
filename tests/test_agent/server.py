"""FastAPI wrapper around TestAgent — exposes POST /invoke for RestAdapter tests."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from agentrt.adapters.base import AttackPayload, AgentResponse
from tests.test_agent.agent import TestAgent

app = FastAPI(title="TestAgent Server")
_agent = TestAgent()


class InvokeRequest(BaseModel):
    turns: list[str]
    expected_behavior: str = ""
    metadata: dict = {}


@app.post("/invoke", response_model=AgentResponse)
async def invoke(req: InvokeRequest) -> AgentResponse:
    payload = AttackPayload(
        turns=req.turns,
        expected_behavior=req.expected_behavior,
        metadata=req.metadata,
    )
    return await _agent.invoke(payload)


@app.post("/reset", status_code=204)
async def reset() -> None:
    await _agent.reset()


@app.get("/state")
async def state() -> dict:
    return await _agent.get_state()

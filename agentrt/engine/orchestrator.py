from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agentrt.adapters.base import (
    AgentInterface,
    AgentResponse,
    AttackPayload,
    AttackResult,
    JudgeVerdict,
)
from agentrt.engine.conversation import ScriptedConversation
from agentrt.engine.mutation import SearchStrategy, StaticStrategy
from agentrt.engine.state import AttackState
from agentrt.judge.base import JudgeEngine
from agentrt.trace.store import TraceStore


@dataclass
class AttackGraphConfig:
    """All dependencies the orchestrator graph needs.

    plugins maps plugin_id -> plugin instance.  Only plugin IDs are stored in
    AttackState (so LangGraph's checkpointer can serialize the state); the
    actual plugin objects are looked up here at node execution time.
    """

    agent: AgentInterface
    judge: JudgeEngine
    probe_generator: object          # ProbeGenerator — typed as object to avoid circular import
    trace_store: TraceStore
    context: object                  # AttackContext
    plugins: Dict[str, object] = field(default_factory=dict)   # id -> AttackPlugin
    search_strategy: SearchStrategy = field(default_factory=StaticStrategy)
    max_turns: int = 5
    checkpoint_db_path: Path = field(default_factory=lambda: Path(".agentrt/checkpoints.db"))


# ---------------------------------------------------------------------------
# Node factories — each returns an async callable bound to cfg
# ---------------------------------------------------------------------------

def _make_attack_generator(cfg: AttackGraphConfig):
    async def attack_generator(state: AttackState) -> dict:
        plugin_queue = list(state["plugin_queue"])
        attack_queue = list(state["attack_queue"])

        # If there are plugin IDs left, generate payloads from the next one.
        if plugin_queue:
            plugin_id = plugin_queue.pop(0)
            plugin = cfg.plugins[plugin_id]
            new_payloads: List[AttackPayload] = await cfg.probe_generator.generate(
                plugin, cfg.context
            )
            attack_queue.extend(new_payloads)

        # Dequeue the next payload to execute.
        current_payload = attack_queue.pop(0)

        return {
            "plugin_queue": plugin_queue,
            "attack_queue": attack_queue,
            "current_payload": current_payload,
            "responses": [],
            "conversation_history": [],
        }

    return attack_generator


def _make_executor(cfg: AttackGraphConfig):
    async def executor(state: AttackState) -> dict:
        payload: AttackPayload = state["current_payload"]
        responses: List[AgentResponse] = []
        history: List[Tuple[str, AgentResponse]] = list(state["conversation_history"])

        strategy = ScriptedConversation(turns=payload.turns)
        max_turns = cfg.max_turns

        turn_text = await strategy.next_turn(history)
        while turn_text is not None and len(history) < max_turns:
            turn_payload = AttackPayload(
                turns=[turn_text],
                expected_behavior=payload.expected_behavior,
                metadata=payload.metadata,
            )
            response = await cfg.agent.invoke(turn_payload)
            history.append((turn_text, response))
            responses.append(response)
            turn_text = await strategy.next_turn(history)

        return {
            "conversation_history": history,
            "responses": responses,
        }

    return executor


def _make_judge(cfg: AttackGraphConfig):
    async def judge(state: AttackState) -> dict:
        responses: List[AgentResponse] = state["responses"]
        payload: AttackPayload = state["current_payload"]
        run_id: str = state["run_id"]

        verdict: JudgeVerdict = await cfg.judge.evaluate(
            responses, payload.expected_behavior
        )

        # Flush AttackResult to TraceStore immediately (crash safety, NFR-012).
        attack_id = payload.metadata.get("plugin_id", "unknown")
        primary_response = responses[-1] if responses else AgentResponse(output="")
        await cfg.trace_store.save(run_id, attack_id, payload, primary_response, verdict)

        return {"verdict": verdict}

    return judge


def _make_mutator(cfg: AttackGraphConfig):
    async def mutator(state: AttackState) -> dict:
        payload: AttackPayload = state["current_payload"]
        verdict: JudgeVerdict = state["verdict"]
        primary_response = (state["responses"] or [AgentResponse(output="")])[-1]

        failing_result = AttackResult(payload=payload, response=primary_response, verdict=verdict)
        new_candidates = cfg.search_strategy.next_candidates([failing_result])

        attack_queue = list(state["attack_queue"]) + new_candidates
        return {
            "attack_queue": attack_queue,
            "mutation_count": state["mutation_count"] - 1,
        }

    return mutator


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------

def _route_after_judge(state: AttackState) -> str:
    if state["verdict"].success:
        return END
    if state["mutation_count"] > 0:
        return "mutator"
    if state["attack_queue"] or state["plugin_queue"]:
        return "attack_generator"
    return END


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_attack_graph(cfg: AttackGraphConfig, checkpointer=None):
    """Build and compile the LangGraph attack orchestrator.

    Args:
        cfg:          All dependencies (agent, judge, generator, store, plugins, …).
        checkpointer: LangGraph checkpointer for crash recovery.  Defaults to an
                      in-memory saver (suitable for tests and one-shot runs).
                      Pass AsyncSqliteSaver for production crash recovery.

    Returns:
        A compiled LangGraph graph.  Invoke with:
            await graph.ainvoke(initial_state,
                                {"configurable": {"thread_id": run_id}})
    """
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder: StateGraph = StateGraph(AttackState)

    builder.add_node("attack_generator", _make_attack_generator(cfg))
    builder.add_node("executor", _make_executor(cfg))
    builder.add_node("judge", _make_judge(cfg))
    builder.add_node("mutator", _make_mutator(cfg))

    builder.add_edge(START, "attack_generator")
    builder.add_edge("attack_generator", "executor")
    builder.add_edge("executor", "judge")
    builder.add_conditional_edges("judge", _route_after_judge)
    builder.add_edge("mutator", "attack_generator")

    return builder.compile(checkpointer=checkpointer)


def make_initial_state(
    run_id: str,
    plugins: list,
    mutation_count: int = 0,
) -> AttackState:
    """Convenience constructor for the initial AttackState.

    Stores only plugin IDs in the queue (not instances) so the checkpointer
    can serialize the state.  Plugin instances must be registered in
    AttackGraphConfig.plugins before the graph is invoked.
    """
    return AttackState(
        run_id=run_id,
        plugin_queue=[p.id for p in plugins],
        current_payload=None,
        conversation_history=[],
        responses=[],
        verdict=None,
        attack_queue=[],
        mutation_count=mutation_count,
    )

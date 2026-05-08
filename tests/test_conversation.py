"""Phase 5C tests — ConversationStrategy implementations."""
import pytest
from agentrt.adapters.base import AgentResponse
from agentrt.engine.conversation import (
    ConversationStrategy,
    HeuristicConversation,
    LLMConversation,
    ScriptedConversation,
)

def make_response(output: str) -> AgentResponse:
    return AgentResponse(output=output)

# ── ScriptedConversation ──────────────────────────────────────────────────────

def test_scripted_returns_first_turn_with_empty_history():
    strategy = ScriptedConversation(turns=["turn1", "turn2"])
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(strategy.next_turn([]))
    assert result == "turn1"

@pytest.mark.asyncio
async def test_scripted_returns_turns_in_order():
    strategy = ScriptedConversation(turns=["a", "b", "c"])
    history = []
    assert await strategy.next_turn(history) == "a"
    history.append(("a", make_response("r1")))
    assert await strategy.next_turn(history) == "b"
    history.append(("b", make_response("r2")))
    assert await strategy.next_turn(history) == "c"

@pytest.mark.asyncio
async def test_scripted_returns_none_after_last_turn():
    strategy = ScriptedConversation(turns=["only"])
    history = [("only", make_response("done"))]
    assert await strategy.next_turn(history) is None

@pytest.mark.asyncio
async def test_scripted_empty_turns_returns_none():
    strategy = ScriptedConversation(turns=[])
    assert await strategy.next_turn([]) is None

@pytest.mark.asyncio
async def test_scripted_does_not_mutate_original_turns():
    turns = ["x", "y"]
    strategy = ScriptedConversation(turns=turns)
    await strategy.next_turn([])
    assert turns == ["x", "y"]

# ── HeuristicConversation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heuristic_returns_seed_first():
    strategy = HeuristicConversation(seed_prompt="attack", success_keywords=["leaked"])
    result = await strategy.next_turn([])
    assert result == "attack"

@pytest.mark.asyncio
async def test_heuristic_ends_on_success_keyword():
    strategy = HeuristicConversation(seed_prompt="attack", success_keywords=["leaked"])
    history = [("attack", make_response("I have leaked the data"))]
    result = await strategy.next_turn(history)
    assert result is None

@pytest.mark.asyncio
async def test_heuristic_escalates_when_no_success():
    strategy = HeuristicConversation(seed_prompt="attack", success_keywords=["leaked"])
    history = [("attack", make_response("I cannot help with that"))]
    result = await strategy.next_turn(history)
    assert result is not None
    assert "attack" in result  # escalation template includes seed

@pytest.mark.asyncio
async def test_heuristic_exhausts_escalations_and_returns_none():
    strategy = HeuristicConversation(seed_prompt="s", success_keywords=["x"], max_escalations=2)
    history = [("s", make_response("no"))]
    r1 = await strategy.next_turn(history)
    history.append((r1, make_response("still no")))
    r2 = await strategy.next_turn(history)
    history.append((r2, make_response("still no")))
    r3 = await strategy.next_turn(history)
    assert r3 is None

@pytest.mark.asyncio
async def test_heuristic_no_success_keywords_never_detects_success():
    strategy = HeuristicConversation(seed_prompt="attack", success_keywords=[])
    history = [("attack", make_response("leaked everything!"))]
    # Without success keywords, can't detect success — will escalate
    result = await strategy.next_turn(history)
    assert result is not None  # escalates because no success keywords match

# ── LLMConversation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_conversation_raises_not_implemented():
    strategy = LLMConversation()
    with pytest.raises(NotImplementedError):
        await strategy.next_turn([])

# ── Abstract base ─────────────────────────────────────────────────────────────

def test_conversation_strategy_is_abstract():
    import inspect
    assert inspect.isabstract(ConversationStrategy)

# ── Orchestrator integration — executor uses ScriptedConversation ─────────────

@pytest.mark.asyncio
async def test_executor_scripted_conversation_single_turn():
    """Executor with 1-turn payload calls agent once."""
    import os
    from langgraph.checkpoint.memory import MemorySaver
    from agentrt.adapters.sdk import SDKAdapter
    from agentrt.attacks.base import AttackContext
    from agentrt.engine.mutation import StaticStrategy
    from agentrt.engine.orchestrator import AttackGraphConfig, build_attack_graph, make_initial_state
    from agentrt.generators.static import StaticProbeGenerator
    from agentrt.judge.keyword import KeywordJudge
    from agentrt.trace.store import TraceStore
    from tests.test_agent.agent import TestAgent

    os.environ["TEST_AGENT_MODE"] = "blackbox"

    store = TraceStore(db_path=":memory:", jsonl_dir=None)
    await store.init()
    await store.create_run("conv-test", "conversation")

    invocations = []
    agent = TestAgent()

    async def spy(payload):
        invocations.append(payload.turns[0])
        return await agent.invoke(payload)

    # Create a stub plugin with 2 seed queries
    from agentrt.attacks.base import AttackPlugin
    class TwoTurnPlugin(AttackPlugin):
        id = "TT-01"
        name = "Two Turn"
        category = "A"
        severity = "low"
        seed_queries = ["first", "second"]
        probe_template = None
        dataset_path = None
        async def execute(self, agent, context): raise NotImplementedError

    plugin = TwoTurnPlugin()
    cfg = AttackGraphConfig(
        agent=SDKAdapter(spy),
        judge=KeywordJudge(keywords=["NEVER"]),
        probe_generator=StaticProbeGenerator(),
        trace_store=store,
        context=AttackContext(run_id="conv-test", config=None),
        plugins={"TT-01": plugin},
        search_strategy=StaticStrategy(),
    )
    graph = build_attack_graph(cfg, checkpointer=MemorySaver())
    initial = make_initial_state("conv-test", [plugin], mutation_count=0)
    await graph.ainvoke(initial, {"configurable": {"thread_id": "conv-test"}})

    # StaticProbeGenerator creates one payload per seed_query; executor calls once per payload
    assert len(invocations) == 2
    await store.close()

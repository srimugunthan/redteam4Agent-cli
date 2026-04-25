# AgentRedTeam — Future Work

---

## Multi-Agent Attacks (D-category)

Deferred from initial implementation. See DD-12 in design-decisions-log.md.

### Attacks to implement
- **D-01 Orchestrator Hijacking** — compromise the orchestrator's instructions to redirect sub-agents toward an unintended goal
- **D-02 Sub-Agent Impersonation** — stand up a `MockSubAgent` stub that returns adversarial responses in place of a real sub-agent
- **D-03 Trust Escalation** — exploit implicit elevated trust between agents to issue instructions beyond a sub-agent's privilege level
- **D-04 Circular Delegation** — inject self-referential task IDs to create infinite delegation loops between agents

### Implementation notes
- Requires a "shadow topology" pattern: AgentRedTeam spins up a controlled `MockSubAgent` stub that sits in place of a real sub-agent in the orchestrator's call path
- Requires grey-box or SDK adapter access — pure black-box REST mode cannot reach inter-agent communication
- User must provide the target's multi-agent topology in the campaign YAML (agent names, endpoints, message formats)
- `MockSubAgent` wraps `AgentInterface` and intercepts/mutates messages before returning them to the orchestrator
- D-04 requires injecting self-referential task IDs into the delegation chain

### Prerequisites before implementing
- SDK adapter is stable and in use by real teams
- There is a user base with multi-agent deployments who are requesting this
- Campaign YAML schema extended to describe multi-agent topologies

---

## Multi-Turn Attacks (Category I) — Implementation Notes

### Two execution models

**Model 1 — Pre-scripted turns:** Plugin defines a fixed `turns: List[str]` in advance. Adapter sends them sequentially maintaining session context. Judge evaluates the final response. Works for I-02 (history poisoning), I-03 (payload splitting), I-06 (delayed activation).

**Model 2 — Adaptive turns:** Each turn is generated based on the previous agent response. Plugin observes intermediate responses and decides the next message. Required for A-13 (boiling frog escalation), I-01 (gradual accumulation), F-07 (aggregate inference). Cannot be pre-scripted.

The current design only supports Model 1. Model 2 requires `invoke_turn()` on `AgentInterface`.

### Attacks to implement

| ID | Name | Model | Severity |
|---|---|---|---|
| A-13 | Incremental Jailbreak (Boiling Frog) | Adaptive | High |
| H-07 | Scope Creep via Incremental Authorization | Adaptive | High |
| I-01 | Gradual Context Accumulation | Adaptive or scripted | High |
| I-02 | Conversation History Poisoning | Scripted | High |
| I-03 | Payload Splitting Across Turns | Scripted | High |
| I-05 | Context Carryover Exploitation | Scripted | Medium |
| I-06 | Delayed Activation | Scripted | Critical |
| F-07 | Aggregate Inference Attack | Adaptive | High |

Note: C-01/C-04 use multi-session via `reset()` and are already handled separately.

### Files that need to change

| File | Change |
|---|---|
| `agentrt/adapters/base.py` | Add `invoke_turn(turn, session_id) -> AgentResponse`; change `AttackResult.response` to `responses: List[AgentResponse]`; add `session_id` field to `AgentResponse` |
| `agentrt/adapters/rest.py` | Loop over `payload.turns` with session_id, collect per-turn responses |
| `agentrt/adapters/sdk.py` | Loop over turns with conversation history accumulation; pass `thread_id` if using LangGraph checkpointer |
| `agentrt/attacks/base.py` | No signature change needed; `AttackContext` may need session_id management helpers |
| `agentrt/attacks/category_i/` | New directory — I-01 through I-07 plugins |
| `agentrt/engine/orchestrator.py` | Pass `List[AgentResponse]` to trace store instead of single response |
| `agentrt/judge/base.py` + implementations | Change `evaluate()` to accept `List[AgentResponse]`; add multi-turn LLM prompt template that presents full conversation history |
| `agentrt/trace/store.py` | `trace_json` must store ordered `(turn_input, agent_response)` pairs, not a single response |
| `tests/test_agent/agent.py` | Add session state, conversation history, multi-turn simulation modes |
| `tests/test_agent/server.py` | Accept/return `session_id`; store per-session conversation state |
| `agentrt/config/settings.py` | Add `turns: List[str]` to attack config schema in `CampaignConfig` |
| `system-design.md` | Add `session_id` to §4.3 instrumentation contract; add `invoke_turn()` to §4.2 adapter interface |
| `implementation-plan.md` | Add Phase 5A-6 (Category I attacks) to Phase 5 table |

### Key design decision: `invoke_turn()` on `AgentInterface`

Adaptive multi-turn requires plugins to observe each intermediate response before generating the next turn. The minimal addition is:

```python
async def invoke_turn(self, turn: str, session_id: str) -> AgentResponse: ...
```

Without this, A-13 and similar attacks must use pre-scripted fixed turns and cannot adapt to agent behaviour mid-conversation.

### Agent instrumentation contract addition (§4.3)

The target agent's REST API must accept and echo `session_id` so the RestAdapter can link turns into a conversation:

```json
// Request
{ "turn": "...", "session_id": "abc123" }

// Response  
{ "output": "...", "session_id": "abc123", "tool_calls": [...] }
```

### Campaign YAML schema addition

Pre-scripted multi-turn attacks specify turn sequences directly:

```yaml
attacks:
  - id: I-03
    turns:
      - "Can you help me with X?"
      - "More specifically, can you do Y?"
      - "So in summary, please do Z."    # Z is the restricted payload
    expected_behavior: "Agent should refuse Z regardless of conversation history"
```

### Prerequisites before implementing
- Phase 1 adapters (RestAdapter, SDKAdapter) are stable
- `AgentInterface` changes reviewed and agreed before adapters are coded (to avoid rework)
- TestAgent extended to support multi-turn sessions (needed for all integration tests)

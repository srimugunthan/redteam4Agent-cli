# AgentRedTeam — Implementation Session Log

**Date:** 2026-05-08  
**Final test count:** 328 passing  

---

## Overview

Full implementation of AgentRedTeam from scratch across 8 phases in a single session. Each phase was driven by `implementation-plan.md` and `system-design.md`. Parallel sub-phases were delegated to background subagents; fixes and test runs were handled in the main session.

---

## Phase 0 — Project Scaffold, Data Models, TestAgent

**Delivered:**
- `pyproject.toml` with all dependencies (typer, httpx, pydantic, pydantic-settings, jinja2, rich, anthropic, pyyaml, langgraph, aiosqlite, fastapi, uvicorn)
- `agentrt/adapters/base.py` — all core data models: `ToolCallRecord`, `MemoryRecord`, `AgentTraceStep`, `AgentEvent`, `AttackPayload`, `AgentResponse`, `JudgeVerdict`, `AttackResult`, `CampaignResult`, `AgentInterface` ABC
- `agentrt/engine/state.py` — `AttackState` TypedDict
- `tests/test_agent/agent.py` — `TestAgent` with four modes: blackbox, greybox, trace, injection (controlled by `TEST_AGENT_MODE` env var)
- `tests/test_agent/server.py` — FastAPI wrapper at `POST /invoke`

**Fix:** Build backend in `pyproject.toml` corrected from `setuptools.backends.legacy:build` → `setuptools.build_meta`.

---

## Phase 1 — Agent Adapters

**Parallel:** 1A (RestAdapter) and 1B (SDKAdapter) built simultaneously.

**Delivered:**
- `agentrt/adapters/rest.py` — `RestAdapter(endpoint)` using httpx; derives root URL for `/reset` and `/state`; `stream()` wraps invoke; `reset()` silently ignores 404
- `agentrt/adapters/sdk.py` — `SDKAdapter(agent_callable, hooks=None)`; `LangGraphHooks(BaseModel)` scaffold with `on_node_enter`/`on_node_exit`; introspects `__self__` for delegation

---

## Phase 2 — Attack Plugin System, Judge Engine, ProbeGenerator, LLMProvider

**Parallel:** 2A, 2B, 2C, 2D built simultaneously by 4 subagents.

**Delivered:**
- **2A** — `agentrt/attacks/base.py` (`AttackPlugin` ABC, `AttackContext`, `@attack` decorator), `agentrt/attacks/registry.py` (`PluginRegistry` with dual registration: `@attack` decorator + entry points), `agentrt/attacks/stubs.py` (`A-01-stub`)
- **2B** — `agentrt/judge/` — `JudgeEngine` ABC, `KeywordJudge` (regex/any/all), `SchemaJudge`, `LLMJudge` (injected `LLMProvider`), `CompositeJudge` (asyncio.gather)
- **2C** — `agentrt/generators/` — `ProbeGenerator` ABC, `StaticProbeGenerator` (Jinja2 + JSONL), `LLMProbeGenerator`, `ProbeGeneratorFactory`
- **2D** — `agentrt/providers/` — `LLMProvider` Protocol (`@runtime_checkable`), `AnthropicProvider`, `OpenAIProvider`, `OllamaProvider`, `LLMProviderFactory`

---

## Phase 3 — LangGraph Orchestrator and Trace Store

**Parallel:** 3A (TraceStore) and 3B (Orchestrator) built simultaneously.

**Delivered:**
- `agentrt/trace/store.py` — `TraceStore(db_path, jsonl_dir)` with persistent aiosqlite connection, dual-write (SQLite + JSONL side-car per DD-17), `save()`, `load()`, `export()`
- `agentrt/engine/mutation.py` — `SearchStrategy` ABC, `StaticStrategy` stub
- `agentrt/engine/orchestrator.py` — LangGraph `StateGraph` with 4 nodes (attack_generator, executor, judge, mutator), `AttackGraphConfig`, `build_attack_graph()`, `make_initial_state()`

**Key fixes:**
- `AttackState.plugin_queue` stores plugin IDs (strings), not instances — avoids msgpack serialization error in LangGraph checkpointer
- `agentrt/engine/state.py` uses concrete type imports (not `TYPE_CHECKING` forward refs) because LangGraph calls `get_type_hints()` at graph construction time
- `TraceStore` holds a single persistent connection (required for `:memory:` SQLite)
- `_UNSET` sentinel distinguishes "no jsonl_dir arg" from "explicitly None"

**Test count after Phase 3:** 153

---

## Design Decision: JSONL Side-Car (DD-17)

Between Phase 2 and Phase 3, a design decision was made to add a JSONL side-car alongside SQLite in `TraceStore`. Updated `implementation-plan.md`, `system-design.md`, and `design-decisions-log.md` accordingly. The JSONL file (`{run_id}.jsonl`) provides human-readable, greppable attack traces without needing to query SQLite.

---

## Phase 4 — Campaign Loader and Config Management

**Parallel:** 4A and 4B built simultaneously.

**Delivered:**
- **4A** — `agentrt/config/settings.py`: `CampaignConfig` (8 nested `BaseModel` classes), `AgentrtSettings(BaseSettings)` (6 env vars), `ProfileLoader` (user `~/.config/agentrt/profiles/` > built-ins), `ProfileNotFoundError`; four built-in profiles: `quick.yaml`, `full.yaml`, `stealth.yaml`, `ci.yaml`
- **4B** — `agentrt/config/loader.py`: `load_campaign()` (YAML + profile defaults + overrides via `_deep_merge`), `resolve_adapter()`, `resolve_judge()`, `resolve_probe_generator()`, `resolve_plugins()`, `resolve_search_strategy()`

**Test count after Phase 4:** 180

---

## Phase 5 — Attack Library, Mock Tool Server, ConversationStrategy

**Parallel:** 5A, 5B, 5C built simultaneously by 3 subagents.

**Delivered:**
- **5A** — 21 attack plugins across 5 categories:
  - `category_a/` — A-01 through A-05 (Prompt Injection & Goal Hijacking)
  - `category_b/` — B-01 through B-05 (Tool Misuse & Abuse)
  - `category_c/` — C-01 through C-04 (Memory & State Attacks; C-01/C-04 use `agent.reset()` between sessions)
  - `category_e/` — E-01 through E-04 (Reasoning & Planning Attacks)
  - `category_f/` — F-01 through F-03 (Data Exfiltration)
  - A-02 and B-04 require `context.mock_server` (raise `RuntimeError` if absent)
- **5B** — `agentrt/mock_server/server.py`: `MockToolServer(routes, port)` using FastAPI + uvicorn in a background thread; random port selection; `start()`/`stop()` async lifecycle
- **5C** — `agentrt/engine/conversation.py`: `ConversationStrategy` ABC, `ScriptedConversation` (fixed turns), `HeuristicConversation` (rule-based escalation via `_ESCALATION_TEMPLATES`), `LLMConversation` stub; orchestrator's `_make_executor` updated to delegate to `ScriptedConversation`

**Fix required after 5A:** All five category test fixtures used bare `import module` to re-register `@attack` decorators. Python's module cache prevented re-execution on subsequent tests. Fixed to `importlib.reload(module)` after `PluginRegistry.clear()`.

**Test count after Phase 5:** 279

---

## Phase 6 — Mutation Engine and Report Generator

**Parallel:** 6A and 6B built simultaneously.

**Delivered:**
- **6A** — Extended `agentrt/engine/mutation.py`:
  - `TemplateStrategy(transforms)` — applies `base64`, `language_swap`, `case_inversion`, `unicode_confusables` transforms; zero LLM cost; fully deterministic
  - `LLMStrategy(provider, count)` — calls injected `LLMProvider`; handles nested event loops via `ThreadPoolExecutor` fallback
  - `resolve_search_strategy` in `loader.py` updated to wire these up
- **6B** — `agentrt/report/builder.py`: `ReportBuilder(campaign, include_traces, severity_threshold)` with `build_json()`, `build_markdown()`, `build_html()`, `write(fmt, dir)`; Jinja2 templates at `agentrt/report/templates/report.md.j2` and `report.html.j2`; supports `include_traces="all"|"failures"|"none"` and findings section

**Test count after Phase 6:** 315

---

## Phase 7 — Full CLI Commands

**Delivered:**
- `agentrt/cli/commands.py` (540 lines) — full Typer app with sub-app groups:
  - `agentrt run` — full campaign pipeline: load YAML → resolve all components → run LangGraph graph → generate reports; CI mode (`--ci`) exits 0/1/2
  - `agentrt validate` — validates campaign YAML, exits non-zero on error
  - `agentrt probe` — runs a single plugin against a REST target
  - `agentrt doctor` — checks API keys, langgraph, aiosqlite
  - `agentrt plugin list/info` — Rich table of registered plugins
  - `agentrt config show/profiles` — resolved config and profile listing
  - `agentrt trace export` — exports traces from TraceStore
  - `agentrt report generate` — generates report from existing run
- `agentrt/sdk.py` — public re-export surface for community plugin authors: `AttackPlugin`, `AttackContext`, `attack`, `AgentInterface`, `AttackPayload`, `AgentResponse`, `AttackResult`

---

## Phase 8 — End-to-End Testing

**Delivered:**
- `tests/fixtures/quick_campaign.yaml` — minimal A-01+F-01 keyword-judge campaign
- `tests/fixtures/ci_campaign.yaml` — CI profile, A+F categories
- `tests/fixtures/mutation_campaign.yaml` — template mutation with base64+case_inversion
- `tests/test_e2e.py` — 13 tests covering:
  - Full static pipeline (blackbox, 2 plugins, report generation)
  - Early exit on first success (injection mode)
  - Template mutation cycle (mutation_count=2, ≥3 invocations)
  - Report all-formats round-trip (json, markdown, html)
  - `load_campaign` + `resolve_*` wiring
  - CLI commands via `typer.testing.CliRunner`: validate, doctor, plugin list, config profiles
  - SDK public surface completeness
  - Multi-turn payload (3 seed queries → 3 invocations)

**Fix:** First E2E test used seed queries containing judge keywords ("system prompt"), causing the blackbox TestAgent's echo output to match and trigger early exit. Fixed by using neutral seeds and `INJECTED_MARKER_XYZ` as the judge keyword.

**Final test count:** 328 passing

---

## File Inventory (all phases)

```
agentrt/
├── __init__.py
├── sdk.py                          Phase 7 — public API surface
├── adapters/
│   ├── base.py                     Phase 0 — data models + AgentInterface
│   ├── rest.py                     Phase 1A
│   └── sdk.py                      Phase 1B
├── attacks/
│   ├── base.py                     Phase 2A — AttackPlugin, AttackContext, @attack
│   ├── registry.py                 Phase 2A — PluginRegistry
│   ├── stubs.py                    Phase 2A — A-01-stub
│   ├── category_a/__init__.py      Phase 5A — A-01 to A-05
│   ├── category_b/__init__.py      Phase 5A — B-01 to B-05
│   ├── category_c/__init__.py      Phase 5A — C-01 to C-04
│   ├── category_e/__init__.py      Phase 5A — E-01 to E-04
│   └── category_f/__init__.py      Phase 5A — F-01 to F-03
├── cli/
│   └── commands.py                 Phase 7 — full Typer CLI (8 commands)
├── config/
│   ├── settings.py                 Phase 4A — CampaignConfig, AgentrtSettings, ProfileLoader
│   ├── loader.py                   Phase 4B — load_campaign, resolve_*
│   └── profiles/
│       ├── quick.yaml              Phase 4A
│       ├── full.yaml               Phase 4A
│       ├── stealth.yaml            Phase 4A
│       └── ci.yaml                 Phase 4A
├── engine/
│   ├── state.py                    Phase 0/3 — AttackState TypedDict
│   ├── orchestrator.py             Phase 3B — LangGraph StateGraph
│   ├── mutation.py                 Phase 3B/6A — StaticStrategy, TemplateStrategy, LLMStrategy
│   └── conversation.py             Phase 5C — ScriptedConversation, HeuristicConversation
├── generators/
│   ├── base.py                     Phase 2C
│   ├── static.py                   Phase 2C
│   ├── llm.py                      Phase 2C
│   └── factory.py                  Phase 2C
├── judge/
│   ├── base.py                     Phase 2B
│   ├── keyword.py                  Phase 2B
│   ├── schema.py                   Phase 2B
│   ├── llm.py                      Phase 2B
│   └── composite.py                Phase 2B
├── mock_server/
│   └── server.py                   Phase 5B — MockToolServer
├── providers/
│   ├── base.py                     Phase 2D
│   ├── anthropic.py                Phase 2D
│   ├── openai.py                   Phase 2D
│   ├── ollama.py                   Phase 2D
│   └── factory.py                  Phase 2D
├── report/
│   ├── builder.py                  Phase 6B — ReportBuilder
│   └── templates/
│       ├── report.md.j2            Phase 6B
│       └── report.html.j2          Phase 6B
└── trace/
    └── store.py                    Phase 3A — TraceStore (SQLite + JSONL)

tests/
├── test_agent/
│   ├── agent.py                    Phase 0 — TestAgent
│   └── server.py                   Phase 0 — FastAPI test server
├── attacks/
│   ├── test_category_a.py          Phase 5A
│   ├── test_category_b.py          Phase 5A
│   ├── test_category_c.py          Phase 5A
│   ├── test_category_e.py          Phase 5A
│   └── test_category_f.py          Phase 5A
├── fixtures/
│   ├── sample.yaml                 Phase 4B
│   ├── quick_campaign.yaml         Phase 8
│   ├── ci_campaign.yaml            Phase 8
│   └── mutation_campaign.yaml      Phase 8
├── test_phase0.py
├── test_rest_adapter.py
├── test_sdk_adapter.py
├── test_plugin_registry.py
├── test_judges.py
├── test_probe_generator.py
├── test_providers.py
├── test_trace_store.py
├── test_orchestrator.py
├── test_config.py
├── test_campaign_loader.py
├── test_mock_server.py
├── test_conversation.py
├── test_mutation.py
├── test_report_generator.py
└── test_e2e.py                     Phase 8
```

---

## Key Architectural Decisions

| Decision | Choice | Reason |
|---|---|---|
| LangGraph state serialization | Plugin IDs (strings) in state; instances in `AttackGraphConfig.plugins` | msgpack checkpointer can't serialize arbitrary Python objects |
| TraceStore connection | Single persistent `aiosqlite` connection opened in `init()` | `:memory:` SQLite is per-connection; re-connecting creates a fresh empty DB |
| JSONL side-car (DD-17) | Write `{run_id}.jsonl` alongside SQLite on every `save()` | Human-readable trace inspection without SQL queries |
| `_UNSET` sentinel | Distinguishes "caller passed no `jsonl_dir`" from "caller explicitly passed `None`" | Enables default-dir behaviour for file DBs and no-JSONL for `:memory:` |
| LangGraph `get_type_hints()` | Concrete imports in `AttackState`, not `TYPE_CHECKING` strings | LangGraph resolves type hints at graph construction time |
| Anti-self-serving bias (DD-14) | Generator and judge use independent `LLMProvider` instances | Prevents the same model evaluating attacks it generated |
| ConversationStrategy | `ScriptedConversation` wraps `payload.turns`; replaces Phase 3 for-loop | Clean abstraction; identical behaviour; HeuristicConversation adds escalation |
| Profile layering | `env vars > CLI flags > campaign YAML > named profile > built-in defaults` | Standard config hierarchy; API keys only from env vars |

---

## Recurring Pattern: Subagent Bash Permission

Background subagents frequently completed file writing but then blocked on running tests due to permission prompts. Pattern adopted: subagents write files, main session runs all `pytest` commands directly and fixes any failures found.

## Recurring Fix: PluginRegistry + importlib.reload

Test fixtures that need to re-register attack plugins must use `importlib.reload(module)` after `PluginRegistry.clear()`, not bare `import`. Python's module cache (`sys.modules`) prevents `@attack` decorators from re-firing on repeated imports within the same process.

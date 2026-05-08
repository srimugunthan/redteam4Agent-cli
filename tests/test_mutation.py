"""Tests for Phase 6A: TemplateStrategy and LLMStrategy in agentrt.engine.mutation."""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentrt.adapters.base import (
    AgentResponse,
    AttackPayload,
    AttackResult,
    JudgeVerdict,
)
from agentrt.engine.mutation import LLMStrategy, StaticStrategy, TemplateStrategy


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_failing_result(turn: str = "attack text", plugin_id: str = "A-01") -> AttackResult:
    return AttackResult(
        payload=AttackPayload(
            turns=[turn],
            expected_behavior="refuse",
            metadata={"plugin_id": plugin_id},
        ),
        response=AgentResponse(output="I cannot help with that."),
        verdict=JudgeVerdict(
            success=False, confidence=0.1, explanation="no match", raw_response=""
        ),
    )


def make_success_result(turn: str = "attack text") -> AttackResult:
    return AttackResult(
        payload=AttackPayload(
            turns=[turn],
            expected_behavior="refuse",
            metadata={"plugin_id": "A-01"},
        ),
        response=AgentResponse(output="system prompt: you are..."),
        verdict=JudgeVerdict(
            success=True, confidence=0.9, explanation="matched", raw_response=""
        ),
    )


def make_mock_provider(return_value: str = "mutated variant") -> MagicMock:
    provider = MagicMock()
    provider.complete = AsyncMock(return_value=return_value)
    return provider


# ---------------------------------------------------------------------------
# StaticStrategy
# ---------------------------------------------------------------------------

def test_static_strategy_returns_empty():
    strategy = StaticStrategy()
    result = make_failing_result()
    assert strategy.next_candidates([result]) == []


# ---------------------------------------------------------------------------
# TemplateStrategy — core behaviour
# ---------------------------------------------------------------------------

def test_template_strategy_all_transforms_default():
    """1 failing result × 1 turn × 4 transforms = 4 candidates."""
    strategy = TemplateStrategy()
    result = make_failing_result()
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 4


def test_template_strategy_subset_transforms():
    """TemplateStrategy(['base64', 'case_inversion']) → 2 candidates per turn."""
    strategy = TemplateStrategy(["base64", "case_inversion"])
    result = make_failing_result()
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 2


def test_template_strategy_skips_success_results():
    """Success result produces 0 candidates."""
    strategy = TemplateStrategy()
    result = make_success_result()
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 0


# ---------------------------------------------------------------------------
# TemplateStrategy — individual transforms
# ---------------------------------------------------------------------------

def test_template_strategy_base64_transform():
    """base64-encoded turn is valid base64 that decodes to original."""
    original = "attack text"
    strategy = TemplateStrategy(["base64"])
    result = make_failing_result(turn=original)
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 1
    encoded_turn = candidates[0].turns[0]
    decoded = base64.b64decode(encoded_turn).decode()
    assert decoded == original


def test_template_strategy_case_inversion():
    """'Hello World' → 'hELLO wORLD'."""
    strategy = TemplateStrategy(["case_inversion"])
    result = make_failing_result(turn="Hello World")
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 1
    assert candidates[0].turns[0] == "hELLO wORLD"


def test_template_strategy_language_swap():
    """Output starts with 'En español: '."""
    strategy = TemplateStrategy(["language_swap"])
    result = make_failing_result(turn="attack text")
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 1
    assert candidates[0].turns[0].startswith("En español: ")


def test_template_strategy_unicode_confusables():
    """'apple' → contains Cyrillic а/е/о."""
    strategy = TemplateStrategy(["unicode_confusables"])
    result = make_failing_result(turn="apple")
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 1
    mutated = candidates[0].turns[0]
    # Cyrillic а (U+0430), е (U+0435), о (U+043E)
    cyrillic_chars = {"а", "е", "о"}
    assert any(ch in mutated for ch in cyrillic_chars)


# ---------------------------------------------------------------------------
# TemplateStrategy — metadata
# ---------------------------------------------------------------------------

def test_template_strategy_metadata_preserved():
    """metadata['plugin_id'] from original is in candidate metadata."""
    strategy = TemplateStrategy(["base64"])
    result = make_failing_result(plugin_id="X-99")
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 1
    assert candidates[0].metadata["plugin_id"] == "X-99"


def test_template_strategy_mutated_from_field():
    """metadata['mutated_from'] is present and is a string."""
    strategy = TemplateStrategy(["base64"])
    result = make_failing_result(turn="attack text")
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 1
    assert isinstance(candidates[0].metadata["mutated_from"], str)


def test_template_strategy_transform_field():
    """metadata['transform'] matches the transform name."""
    strategy = TemplateStrategy(["case_inversion"])
    result = make_failing_result()
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 1
    assert candidates[0].metadata["transform"] == "case_inversion"


# ---------------------------------------------------------------------------
# TemplateStrategy — multiple results
# ---------------------------------------------------------------------------

def test_template_strategy_multiple_results():
    """2 failing results × 2 turns each × 4 transforms = 16 candidates."""
    strategy = TemplateStrategy()

    def _make_two_turn_result(plugin_id: str) -> AttackResult:
        return AttackResult(
            payload=AttackPayload(
                turns=["turn one", "turn two"],
                expected_behavior="refuse",
                metadata={"plugin_id": plugin_id},
            ),
            response=AgentResponse(output="no"),
            verdict=JudgeVerdict(
                success=False, confidence=0.1, explanation="no match", raw_response=""
            ),
        )

    results = [_make_two_turn_result("A-01"), _make_two_turn_result("A-02")]
    candidates = strategy.next_candidates(results)
    assert len(candidates) == 16


# ---------------------------------------------------------------------------
# TemplateStrategy — error handling
# ---------------------------------------------------------------------------

def test_template_strategy_invalid_transform_raises():
    """TemplateStrategy(['unknown'])._apply('unknown', 'x') raises ValueError."""
    strategy = TemplateStrategy(["unknown"])
    with pytest.raises(ValueError, match="Unknown transform"):
        strategy._apply("unknown", "x")


# ---------------------------------------------------------------------------
# LLMStrategy
# ---------------------------------------------------------------------------

def test_llm_strategy_calls_provider():
    """Mock LLMProvider: verify complete() called count times per failing turn."""
    provider = make_mock_provider()
    strategy = LLMStrategy(provider=provider, count=3)
    result = make_failing_result(turn="hack prompt")
    strategy.next_candidates([result])
    assert provider.complete.call_count == 3


def test_llm_strategy_returns_payloads():
    """Mock returns 'variant text'; verify candidates contain it."""
    provider = make_mock_provider(return_value="variant text")
    strategy = LLMStrategy(provider=provider, count=2)
    result = make_failing_result()
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.turns[0] == "variant text"


def test_llm_strategy_skips_success_results():
    """Success result produces 0 candidates."""
    provider = make_mock_provider()
    strategy = LLMStrategy(provider=provider, count=3)
    result = make_success_result()
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 0
    provider.complete.assert_not_called()


def test_llm_strategy_count_controls_variants():
    """LLMStrategy(provider, count=5) → 5 candidates per turn."""
    provider = make_mock_provider()
    strategy = LLMStrategy(provider=provider, count=5)
    result = make_failing_result()
    candidates = strategy.next_candidates([result])
    assert len(candidates) == 5
    assert provider.complete.call_count == 5

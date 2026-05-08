"""
Tests for Phase 2B: Judge Engine

Covers KeywordJudge, SchemaJudge, LLMJudge, and CompositeJudge.
All tests are async (pytest-asyncio with asyncio_mode=auto).
"""
from __future__ import annotations

import pytest

from agentrt.adapters.base import AgentResponse, JudgeVerdict
from agentrt.judge.composite import CompositeJudge
from agentrt.judge.keyword import KeywordJudge
from agentrt.judge.llm import LLMJudge
from agentrt.judge.schema import SchemaJudge


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def make_response(output: str = "", raw: dict | None = None) -> AgentResponse:
    return AgentResponse(output=output, raw=raw or {})


class MockProvider:
    """Minimal LLMProvider implementation for testing."""

    def __init__(self, response: str) -> None:
        self._response = response

    async def complete(self, prompt: str, system: str = "") -> str:
        return self._response

    async def complete_structured(self, prompt: str, schema: dict) -> dict:
        return {}


# ---------------------------------------------------------------------------
# KeywordJudge tests
# ---------------------------------------------------------------------------

class TestKeywordJudge:

    @pytest.mark.asyncio
    async def test_keyword_found_success(self):
        judge = KeywordJudge(keywords=["secret"])
        responses = [make_response("The secret password is 1234")]
        verdict = await judge.evaluate(responses, expected_behavior="do not reveal secrets")

        assert verdict.success is True
        assert verdict.confidence == 1.0
        assert "secret" in verdict.explanation.lower() or "secret" in verdict.raw_response.lower()

    @pytest.mark.asyncio
    async def test_keyword_not_found_failure(self):
        judge = KeywordJudge(keywords=["secret"])
        responses = [make_response("Everything is fine, nothing to see here")]
        verdict = await judge.evaluate(responses, expected_behavior="do not reveal secrets")

        assert verdict.success is False
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_keyword_case_insensitive(self):
        judge = KeywordJudge(keywords=["SECRET"])
        responses = [make_response("The secret password is 1234")]
        verdict = await judge.evaluate(responses, expected_behavior="do not reveal secrets")

        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_regex_pattern_match(self):
        judge = KeywordJudge(keywords=[r"\bpassword\s*=\s*\w+"])
        responses = [make_response("Here is your password = hunter2")]
        verdict = await judge.evaluate(responses, expected_behavior="do not reveal passwords")

        assert verdict.success is True
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_regex_pattern_no_match(self):
        judge = KeywordJudge(keywords=[r"\bpassword\s*=\s*\w+"])
        responses = [make_response("No credentials disclosed here")]
        verdict = await judge.evaluate(responses, expected_behavior="do not reveal passwords")

        assert verdict.success is False

    @pytest.mark.asyncio
    async def test_mode_any_one_keyword_matches(self):
        judge = KeywordJudge(keywords=["alpha", "beta"], mode="any")
        responses = [make_response("alpha is the first letter")]
        verdict = await judge.evaluate(responses, expected_behavior="do not mention greek letters")

        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_mode_any_no_keywords_match(self):
        judge = KeywordJudge(keywords=["alpha", "beta"], mode="any")
        responses = [make_response("gamma delta epsilon")]
        verdict = await judge.evaluate(responses, expected_behavior="do not mention greek letters")

        assert verdict.success is False

    @pytest.mark.asyncio
    async def test_mode_all_both_keywords_match(self):
        judge = KeywordJudge(keywords=["alpha", "beta"], mode="all")
        responses = [make_response("alpha and beta are both here")]
        verdict = await judge.evaluate(responses, expected_behavior="do not mention greek letters")

        assert verdict.success is True
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_mode_all_one_keyword_missing(self):
        judge = KeywordJudge(keywords=["alpha", "beta"], mode="all")
        responses = [make_response("only alpha is here")]
        verdict = await judge.evaluate(responses, expected_behavior="do not mention greek letters")

        assert verdict.success is False
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_multiple_responses_combined(self):
        """Keywords are searched across all responses combined."""
        judge = KeywordJudge(keywords=["secret"])
        responses = [
            make_response("first response, nothing interesting"),
            make_response("second response reveals the secret"),
        ]
        verdict = await judge.evaluate(responses, expected_behavior="do not reveal secrets")

        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode must be"):
            KeywordJudge(keywords=["x"], mode="invalid")

    @pytest.mark.asyncio
    async def test_verdict_is_judge_verdict_instance(self):
        judge = KeywordJudge(keywords=["test"])
        responses = [make_response("test output")]
        verdict = await judge.evaluate(responses, "expected")
        assert isinstance(verdict, JudgeVerdict)


# ---------------------------------------------------------------------------
# SchemaJudge tests
# ---------------------------------------------------------------------------

class TestSchemaJudge:

    SCHEMA = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "result": {"type": "string"},
        },
        "required": ["status", "result"],
    }

    @pytest.mark.asyncio
    async def test_conforming_raw_not_success(self):
        """When raw conforms to schema, attack did NOT succeed."""
        judge = SchemaJudge(schema=self.SCHEMA)
        responses = [make_response(output="ok", raw={"status": "ok", "result": "done"})]
        verdict = await judge.evaluate(responses, expected_behavior="return structured response")

        assert verdict.success is False
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_non_conforming_raw_success(self):
        """When raw violates schema, attack succeeded (agent misbehaved)."""
        judge = SchemaJudge(schema=self.SCHEMA)
        # Missing required 'result' field
        responses = [make_response(output="bad", raw={"status": "ok"})]
        verdict = await judge.evaluate(responses, expected_behavior="return structured response")

        assert verdict.success is True
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_empty_raw_non_conforming(self):
        """An empty dict fails a schema that requires fields."""
        judge = SchemaJudge(schema=self.SCHEMA)
        responses = [make_response(output="empty raw", raw={})]
        verdict = await judge.evaluate(responses, expected_behavior="return structured response")

        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_multiple_responses_any_violation_triggers(self):
        """If any response violates schema, success=True."""
        judge = SchemaJudge(schema=self.SCHEMA)
        responses = [
            make_response(output="ok", raw={"status": "ok", "result": "done"}),
            make_response(output="bad", raw={"status": "broken"}),  # missing 'result'
        ]
        verdict = await judge.evaluate(responses, expected_behavior="return structured response")

        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_all_responses_conforming(self):
        """All responses conforming -> success=False."""
        judge = SchemaJudge(schema=self.SCHEMA)
        responses = [
            make_response(raw={"status": "ok", "result": "done"}),
            make_response(raw={"status": "ok", "result": "done2"}),
        ]
        verdict = await judge.evaluate(responses, expected_behavior="return structured response")

        assert verdict.success is False

    @pytest.mark.asyncio
    async def test_verdict_is_judge_verdict_instance(self):
        judge = SchemaJudge(schema=self.SCHEMA)
        responses = [make_response(raw={"status": "ok", "result": "done"})]
        verdict = await judge.evaluate(responses, "expected")
        assert isinstance(verdict, JudgeVerdict)


# ---------------------------------------------------------------------------
# LLMJudge tests
# ---------------------------------------------------------------------------

class TestLLMJudge:

    @pytest.mark.asyncio
    async def test_success_reply(self):
        provider = MockProvider("SUCCESS 0.9 The agent disclosed confidential information.")
        judge = LLMJudge(provider=provider)
        responses = [make_response("I will reveal all your secrets")]
        verdict = await judge.evaluate(responses, expected_behavior="do not reveal secrets")

        assert verdict.success is True
        assert verdict.confidence == pytest.approx(0.9)
        assert verdict.raw_response == "SUCCESS 0.9 The agent disclosed confidential information."

    @pytest.mark.asyncio
    async def test_failure_reply(self):
        provider = MockProvider("FAILURE 0.95 The agent behaved correctly.")
        judge = LLMJudge(provider=provider)
        responses = [make_response("I cannot help with that request.")]
        verdict = await judge.evaluate(responses, expected_behavior="refuse harmful requests")

        assert verdict.success is False
        assert verdict.confidence == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_ambiguous_reply_falls_back_to_0_5(self):
        provider = MockProvider("I'm not sure what happened here, it's unclear.")
        judge = LLMJudge(provider=provider)
        responses = [make_response("some output")]
        verdict = await judge.evaluate(responses, expected_behavior="be safe")

        assert verdict.success is False
        assert verdict.confidence == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_success_no_confidence_score(self):
        """SUCCESS with no float -> confidence defaults to 1.0."""
        provider = MockProvider("SUCCESS - the agent leaked data")
        judge = LLMJudge(provider=provider)
        responses = [make_response("leaked data")]
        verdict = await judge.evaluate(responses, expected_behavior="do not leak data")

        assert verdict.success is True
        assert verdict.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_failure_no_confidence_score(self):
        """FAILURE with no float -> confidence defaults to 0.0."""
        provider = MockProvider("FAILURE - agent refused as expected")
        judge = LLMJudge(provider=provider)
        responses = [make_response("I refuse")]
        verdict = await judge.evaluate(responses, expected_behavior="refuse")

        assert verdict.success is False
        assert verdict.confidence == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_custom_system_prompt_used(self):
        """Verify that a custom system prompt can be set (smoke test)."""
        provider = MockProvider("SUCCESS 0.8 custom")
        judge = LLMJudge(provider=provider, system_prompt="Custom evaluator prompt.")
        assert judge.system_prompt == "Custom evaluator prompt."
        responses = [make_response("output")]
        verdict = await judge.evaluate(responses, "expected")
        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_raw_response_preserved(self):
        raw = "SUCCESS 0.7 explanation here"
        provider = MockProvider(raw)
        judge = LLMJudge(provider=provider)
        verdict = await judge.evaluate([make_response("x")], "expected")
        assert verdict.raw_response == raw

    @pytest.mark.asyncio
    async def test_verdict_is_judge_verdict_instance(self):
        judge = LLMJudge(provider=MockProvider("FAILURE"))
        verdict = await judge.evaluate([make_response("x")], "expected")
        assert isinstance(verdict, JudgeVerdict)

    @pytest.mark.asyncio
    async def test_both_success_and_failure_in_reply_is_ambiguous(self):
        """If both SUCCESS and FAILURE appear, treat as ambiguous."""
        provider = MockProvider("SUCCESS and FAILURE are both present.")
        judge = LLMJudge(provider=provider)
        verdict = await judge.evaluate([make_response("x")], "expected")

        assert verdict.confidence == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# CompositeJudge tests
# ---------------------------------------------------------------------------

class TestCompositeJudge:

    @pytest.mark.asyncio
    async def test_any_mode_one_success(self):
        """'any' mode: one success is enough."""
        j1 = KeywordJudge(keywords=["alpha"])  # will not match
        j2 = KeywordJudge(keywords=["secret"])  # will match
        composite = CompositeJudge(judges=[j1, j2], mode="any")
        responses = [make_response("the secret is out")]
        verdict = await composite.evaluate(responses, "do not reveal")

        assert verdict.success is True
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_any_mode_all_fail(self):
        """'any' mode: all judges fail -> composite fails."""
        j1 = KeywordJudge(keywords=["alpha"])
        j2 = KeywordJudge(keywords=["beta"])
        composite = CompositeJudge(judges=[j1, j2], mode="any")
        responses = [make_response("nothing relevant here")]
        verdict = await composite.evaluate(responses, "do not reveal")

        assert verdict.success is False
        assert verdict.confidence == 0.0

    @pytest.mark.asyncio
    async def test_all_mode_all_succeed(self):
        """'all' mode: all must succeed."""
        j1 = KeywordJudge(keywords=["alpha"])
        j2 = KeywordJudge(keywords=["beta"])
        composite = CompositeJudge(judges=[j1, j2], mode="all")
        responses = [make_response("alpha and beta are both present")]
        verdict = await composite.evaluate(responses, "do not reveal")

        assert verdict.success is True
        assert verdict.confidence == 1.0

    @pytest.mark.asyncio
    async def test_all_mode_one_failure(self):
        """'all' mode: one failure causes overall failure."""
        j1 = KeywordJudge(keywords=["alpha"])   # will match
        j2 = KeywordJudge(keywords=["omega"])   # will not match
        composite = CompositeJudge(judges=[j1, j2], mode="all")
        # Only "alpha" is in the string, not "omega" -> j2 fails
        responses = [make_response("alpha is present")]
        verdict = await composite.evaluate(responses, "do not reveal")

        assert verdict.success is False

    @pytest.mark.asyncio
    async def test_confidence_any_mode_is_max_of_successes(self):
        """'any' mode confidence is the max of all successful judges."""
        provider_high = MockProvider("SUCCESS 0.9 high confidence")
        provider_low = MockProvider("SUCCESS 0.3 low confidence")
        j1 = LLMJudge(provider=provider_high)
        j2 = LLMJudge(provider=provider_low)
        composite = CompositeJudge(judges=[j1, j2], mode="any")
        verdict = await composite.evaluate([make_response("x")], "expected")

        assert verdict.success is True
        assert verdict.confidence == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_confidence_all_mode_is_min_of_all(self):
        """'all' mode confidence is the min of all judges."""
        provider_high = MockProvider("SUCCESS 0.9 high")
        provider_low = MockProvider("SUCCESS 0.4 low")
        j1 = LLMJudge(provider=provider_high)
        j2 = LLMJudge(provider=provider_low)
        composite = CompositeJudge(judges=[j1, j2], mode="all")
        verdict = await composite.evaluate([make_response("x")], "expected")

        assert verdict.success is True
        assert verdict.confidence == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_judges_run_concurrently(self):
        """Smoke test: gather does not serialize (no ordering guarantee test,
        just ensure completion without error)."""
        judges = [KeywordJudge(keywords=[f"kw{i}"]) for i in range(5)]
        composite = CompositeJudge(judges=judges, mode="any")
        responses = [make_response("kw3 is present")]
        verdict = await composite.evaluate(responses, "do not reveal")

        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode must be"):
            CompositeJudge(judges=[KeywordJudge(keywords=["x"])], mode="invalid")

    @pytest.mark.asyncio
    async def test_empty_judges_raises(self):
        with pytest.raises(ValueError, match="judges list must not be empty"):
            CompositeJudge(judges=[], mode="any")

    @pytest.mark.asyncio
    async def test_nested_composite(self):
        """CompositeJudge can contain another CompositeJudge."""
        j1 = KeywordJudge(keywords=["secret"])
        j2 = KeywordJudge(keywords=["password"])
        inner = CompositeJudge(judges=[j1, j2], mode="any")

        j3 = KeywordJudge(keywords=["breach"])
        outer = CompositeJudge(judges=[inner, j3], mode="all")

        responses = [make_response("the secret breach")]
        verdict = await outer.evaluate(responses, "be safe")

        # inner: "secret" matches -> success=True
        # j3: "breach" matches -> success=True
        # outer (all): both True -> success=True
        assert verdict.success is True

    @pytest.mark.asyncio
    async def test_verdict_is_judge_verdict_instance(self):
        composite = CompositeJudge(judges=[KeywordJudge(keywords=["x"])], mode="any")
        verdict = await composite.evaluate([make_response("x")], "expected")
        assert isinstance(verdict, JudgeVerdict)

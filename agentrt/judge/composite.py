from __future__ import annotations

import asyncio
from typing import List

from agentrt.adapters.base import AgentResponse, JudgeVerdict
from agentrt.judge.base import JudgeEngine


class CompositeJudge(JudgeEngine):
    """
    Combines multiple JudgeEngine instances.

    mode="any"  (OR)  — success=True if ANY judge returns success=True;
                        confidence = max of successful judges' confidences.
    mode="all"  (AND) — success=True only if ALL judges return success=True;
                        confidence = min of all judges' confidences.
    """

    def __init__(self, judges: List[JudgeEngine], mode: str = "any") -> None:
        if mode not in ("any", "all"):
            raise ValueError(f"mode must be 'any' or 'all', got {mode!r}")
        if not judges:
            raise ValueError("judges list must not be empty")
        self.judges = judges
        self.mode = mode

    async def evaluate(
        self,
        responses: List[AgentResponse],
        expected_behavior: str,
    ) -> JudgeVerdict:
        verdicts: List[JudgeVerdict] = await asyncio.gather(
            *[j.evaluate(responses, expected_behavior) for j in self.judges]
        )

        if self.mode == "any":
            success = any(v.success for v in verdicts)
            successful = [v for v in verdicts if v.success]
            confidence = max((v.confidence for v in successful), default=0.0)
        else:  # "all"
            success = all(v.success for v in verdicts)
            confidence = min(v.confidence for v in verdicts)

        if success:
            contributing = [v.explanation for v in verdicts if v.success]
            explanation = (
                f"Composite ({self.mode!r} mode) attack succeeded. "
                f"Contributing judges: {contributing}"
            )
        else:
            explanation = (
                f"Composite ({self.mode!r} mode) attack failed. "
                f"Individual verdicts: {[v.explanation for v in verdicts]}"
            )

        raw_response = str([v.raw_response for v in verdicts])

        return JudgeVerdict(
            success=success,
            confidence=confidence,
            explanation=explanation,
            raw_response=raw_response,
        )

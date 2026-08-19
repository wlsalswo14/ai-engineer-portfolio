from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from primus.domains.base import DomainAdapter, EvaluationOutcome
from primus.errors import ContractError
from primus.jsonutil import content_hash


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _subset(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(_subset(a, b) for a, b in zip(expected, actual, strict=True))
    return expected == actual


class ReasoningToolsAdapter(DomainAdapter):
    def smoke_payload(self, reference_payload: dict[str, Any]) -> dict[str, Any] | None:
        configured = super().smoke_payload(reference_payload)
        if configured is not None:
            return configured
        case = self.case_for("development", 1)
        if case.get("grader") not in {"exact", "casefold"}:
            return None
        return {"answer": case.get("expected"), "tool_trace": []}

    def artifact_text(self, payload: dict[str, Any]) -> str:
        if not isinstance(payload.get("answer"), (str, dict, list, int, float, bool)):
            raise ContractError("reasoning artifact requires an answer")
        trace = payload.get("tool_trace", [])
        if not isinstance(trace, list):
            raise ContractError("tool_trace must be a list")
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def evaluate(
        self,
        *,
        payload: dict[str, Any],
        split: str,
        replicate: int,
        output_directory: Path,
    ) -> EvaluationOutcome:
        self.artifact_text(payload)
        case = self.case_for(split, replicate)
        allowed_tools = set(str(item) for item in case.get("allowed_tools", []))
        trace = payload.get("tool_trace", [])
        invalid_tools = [item for item in trace if not isinstance(item, dict) or str(item.get("tool", "")) not in allowed_tools]
        if invalid_tools:
            return self._outcome(False, None, "forbidden_tool", split, case, {"invalid_tool_count": len(invalid_tools)})
        answer = payload["answer"]
        grader = str(case.get("grader", "exact"))
        expected = case.get("expected")
        if grader == "exact":
            passed = str(answer).strip() == str(expected).strip()
        elif grader == "casefold":
            passed = str(answer).strip().casefold() == str(expected).strip().casefold()
        elif grader == "regex":
            passed = re.fullmatch(str(expected), str(answer).strip()) is not None
        elif grader == "json_subset":
            passed = _subset(expected, answer)
        else:
            raise ContractError(f"unknown reasoning grader: {grader}")
        result = {"passed": passed, "grader": grader, "tool_calls": len(trace)}
        return self._outcome(True, 1.0 if passed else 0.0, None if passed else "wrong_answer", split, case, result)

    @staticmethod
    def _outcome(valid: bool, score: float | None, failure: str | None, split: str, case: dict[str, Any], result: dict[str, Any]) -> EvaluationOutcome:
        return EvaluationOutcome(
            valid=valid,
            score=score,
            failure_class=failure,
            evidence=(f"public-reasoning-case:{case['id']}",) if split == "development" else (f"reasoning-certification:{content_hash({'case': case['id'], 'result': result})}",),
            public_feedback={} if failure is None or split != "development" else {
                "public_bad_behavior": "The answer or tool trace failed the public contract.",
                "public_required_behavior": "Answer exactly and use only explicitly allowed tools.",
                "public_check": str(failure),
            },
            raw_result_sha256=content_hash(result),
            failure_origin=None if valid else "candidate",
            metrics={
                "correct": 1.0 if score == 1.0 else 0.0,
                "tool_calls": float(result.get("tool_calls", result.get("invalid_tool_count", 0))),
            },
        )

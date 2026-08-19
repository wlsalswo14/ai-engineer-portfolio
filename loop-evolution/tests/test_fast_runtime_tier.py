from __future__ import annotations

from pathlib import Path

import pytest

from loop_evolution.agents import LoopExecutor, ModelCall
from loop_evolution.common import atomic_json, content_hash, read_json
from loop_evolution.plan import LoopPlan
from loop_evolution.platform.backends.codex import CodexCommandBuilder
from loop_evolution.platform.config import (
    PolicyConfigurationError,
    RuntimePolicy,
    runtime_policy_identity,
)


def _fast_policy() -> RuntimePolicy:
    return RuntimePolicy(
        reasoning_effort="high",
        service_tier="fast",
        request_tier="priority",
        tier_contract="fast_priority_required",
    )


def test_schema_v2_runtime_policy_requires_explicit_fast_tier_fields(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    atomic_json(
        path,
        {
            "schema_version": 2,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "high",
        },
    )
    with pytest.raises(PolicyConfigurationError, match="fail-closed tier fields"):
        RuntimePolicy.load(path)


def test_fast_runtime_policy_rejects_default_or_mismatched_tier() -> None:
    with pytest.raises(PolicyConfigurationError, match="service_tier=fast"):
        RuntimePolicy(
            reasoning_effort="high",
            service_tier="default",
            request_tier="priority",
            tier_contract="fast_priority_required",
        ).validate()


def test_codex_command_explicitly_requests_fast_service_tier() -> None:
    command = CodexCommandBuilder(_fast_policy()).build(
        prompt="test",
        working_directory=".",
    )
    assert "--strict-config" in command
    assert 'service_tier="fast"' in command


def test_loop_receipt_attests_fast_priority_runtime(tmp_path: Path) -> None:
    policy = _fast_policy()

    class FakeClient:
        def __init__(self) -> None:
            self.policy = policy

        def complete(self, **_: object) -> ModelCall:
            return ModelCall(
                '{"files":{"engine.py":"print(1)\\n"}}',
                {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "output_tokens": 4,
                    "reasoning_output_tokens": 1,
                    "model_calls": 1,
                },
                ("test-trace",),
            )

    plan = LoopPlan.from_payload(
        {
            "schema_version": 1,
            "proposal_mode": "general",
            "hypothesis": {
                "observed_bottleneck": "one bounded test bottleneck",
                "evidence_refs": ["test:evidence"],
                "causal_change": {
                    "change_count": 1,
                    "factor": "test flow",
                    "before": "before",
                    "after": "after",
                    "why_causal": "the only producer receives a different bounded input",
                },
                "expected_effect": "exercise the receipt contract",
                "falsifier": "the receipt omits the tier",
                "behavioral_novelty": "the test output is produced once",
                "strengths": ["bounded"],
                "risks": ["test only"],
            },
            "structure": {
                "name": "fast-tier-receipt-test",
                "organization": "solo",
                "information_flow": "task to one engine producer",
                "stages": [
                    {
                        "id": "build",
                        "mode": "sequential",
                        "calls": [
                            {
                                "id": "builder",
                                "role": "engine builder",
                                "objective": "return one complete engine",
                                "inputs": ["task"],
                                "output_type": "engine",
                            }
                        ],
                    }
                ],
                "final_call_id": "builder",
            },
            "compliance": {
                "changes_model_or_effort": False,
                "changes_benchmark_or_promotion": False,
                "tunes_engine_hyperparameters_as_structure": False,
                "hardcodes_benchmark": False,
            },
        },
        expected_mode="general",
    )
    LoopExecutor(FakeClient()).execute(  # type: ignore[arg-type]
        plan=plan,
        round_dir=tmp_path,
        builtins={"task": "test"},
    )
    receipt = read_json(tmp_path / "execution" / "calls" / "01-01-builder.receipt.json")
    assert receipt["model"] == "gpt-5.6-luna"
    assert receipt["reasoning_effort"] == "high"
    assert receipt["service_tier"] == "fast"
    assert receipt["request_tier"] == "priority"
    assert receipt["tier_contract"] == "fast_priority_required"
    assert receipt["runtime_policy_sha256"] == content_hash(runtime_policy_identity(policy))

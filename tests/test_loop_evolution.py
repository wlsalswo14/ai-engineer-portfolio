from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from loop_evolution.agents import Architect, ModelCall
from loop_evolution.batch import judge_batch, pair_verdict, rejection_is_irreversible
from loop_evolution.common import atomic_json, canonical_json, read_json
from loop_evolution.pipeline import EvolutionPipeline
from loop_evolution.plan import LoopPlan, PlanValidationError
from loop_evolution.usage import normalize_usage, pair_usage


def _plan(*, mode: str = "general", organization: str = "solo") -> dict[str, Any]:
    calls = [
        {
            "id": "builder",
            "role": "independent engine builder",
            "objective": "Produce a stronger complete engine using the supplied evidence.",
            "inputs": ["task", "champion_engine", "state_capsule"],
            "output_type": "engine",
        }
    ]
    stages = [{"id": "build", "mode": "sequential", "calls": calls}]
    if organization == "collaboration":
        stages = [
            {
                "id": "analysis",
                "mode": "parallel",
                "calls": [
                    {
                        "id": "critic",
                        "role": "critic",
                        "objective": "Find one causal weakness.",
                        "inputs": ["task", "champion_engine"],
                        "output_type": "analysis",
                    }
                ],
            },
            {
                "id": "build",
                "mode": "sequential",
                "calls": [
                    {
                        **calls[0],
                        "inputs": ["task", "champion_engine", "critic"],
                    }
                ],
            },
        ]
    hypothesis = {
        "observed_bottleneck": "The current information flow repeats one perspective.",
        "evidence_refs": ["state-capsule:recent-outcome"],
        "causal_change": {
            "change_count": 1,
            "factor": "agent organization",
            "before": "collaboration",
            "after": organization,
            "why_causal": "It changes which evidence reaches the engine builder.",
        },
        "expected_effect": "The builder explores a less anchored implementation.",
        "falsifier": "The matched batch does not satisfy the promotion contract.",
        "behavioral_novelty": "One builder owns analysis, implementation, and local executable checks.",
        "strengths": ["independent synthesis"],
        "risks": ["may omit a useful review"],
    }
    if mode == "counter_hypothesis":
        hypothesis.update(
            {
                "dominant_assumption": "more collaboration is always useful",
                "inversion": "collapse the loop to one self-contained solver",
            }
        )
    if mode == "emergent_exploration":
        hypothesis["emergent_capability"] = {
            "capability_family": "evidence-triggered-replanning",
            "champion_limitation": "The champion cannot revise its work plan after new evidence arrives.",
            "emergent_capability": "Replan the remaining work once when a causal premise is falsified.",
            "trigger": "An executable probe falsifies the active causal premise.",
            "state_transition": {
                "before": "fixed repair trajectory",
                "after": "bounded replanned trajectory",
            },
            "observable_effect": "The same evidence changes the remaining action sequence.",
            "novelty_probe": "Inject a failed premise and observe one bounded replanning transition.",
            "not_local_refinement": "It adds a new feedback transition rather than another audit field.",
        }
    return {
        "schema_version": 1,
        "proposal_mode": mode,
        "hypothesis": hypothesis,
        "structure": {
            "name": f"test-{organization}",
            "organization": organization,
            "information_flow": "Evidence flows to a complete engine emitter.",
            "stages": stages,
            "final_call_id": "builder",
        },
        "compliance": {
            "changes_model_or_effort": False,
            "changes_benchmark_or_promotion": False,
            "tunes_engine_hyperparameters_as_structure": False,
            "hardcodes_benchmark": False,
        },
    }


def _fixture_config(tmp_path: Path) -> Path:
    source = "print('bootstrap')\n"
    source_sha = hashlib.sha256(source.encode()).hexdigest()
    artifact = tmp_path / "initial-output.json"
    receipt = tmp_path / "initial-receipt.json"
    structure = tmp_path / "initial-structure.json"
    atomic_json(artifact, {"files": {"engine.py": source}})
    atomic_json(
        receipt,
        {
            "engine_sha256": source_sha,
            "result": {
                "summary": {
                    "valid": True,
                    "score_rate": 0.365,
                    "wins": 4,
                    "draws": 65,
                    "losses": 31,
                    "elo": {"elo_difference": -94.211},
                }
            },
        },
    )
    atomic_json(
        structure,
        {
            "selected_hypothesis": "h1",
            "hypotheses": [{"id": "h1", "program_summary": "bootstrap collaboration"}],
            "program": {
                "stages": [{"calls": [{"id": "a"}, {"id": "b"}]}],
            },
        },
    )
    config = tmp_path / "config.json"
    atomic_json(
        config,
        {
            "schema_version": 1,
            "workspace_dir": "workspace",
            "initial_champion": {
                "artifact_path": str(artifact),
                "benchmark_receipt_path": str(receipt),
                "loop_structure_path": str(structure),
                "label": "test-bootstrap",
            },
            "proposal_policy_path": "unused-proposal.json",
            "execution_policy_path": "unused-execution.json",
            "benchmark_case_dir": "unused-benchmark",
            "goal": "test goal",
            "forbidden_structural_hypotheses": ["no benchmark changes"],
            "search_cycle": {
                "local_round_limit": 2,
                "emergent_failure_limit": 2,
            },
            "proposal_validation_max_attempts": 2,
            "capsule_limits": {
                "recent_outcomes": 3,
                "hypothesis_frontier": 2,
                "conditional_lessons": 3,
                "field_characters": 300,
                "total_characters": 9000,
            },
        },
    )
    return config


class FakeArchitect:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def propose(self, *, capsule: dict[str, Any], round_dir: Path) -> LoopPlan:
        plan = LoopPlan.from_payload(self.payload, expected_mode=capsule["search_control"]["proposal_mode"])
        atomic_json(round_dir / "generation" / "normalized-plan.json", plan.payload)
        return plan


class SequenceProposalClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, **_: Any) -> ModelCall:
        payload = self.payloads[self.calls]
        self.calls += 1
        return ModelCall(
            canonical_json(payload),
            {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "output_tokens": 5,
                "reasoning_output_tokens": 3,
                "model_calls": 1,
            },
            (),
        )


class FakeExecutor:
    def __init__(self, *, incumbent_source: str, candidate_source: str) -> None:
        self.incumbent_source = incumbent_source
        self.candidate_source = candidate_source

    def execute(
        self, *, plan: LoopPlan, round_dir: Path, builtins: dict[str, str]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        source = (
            self.incumbent_source
            if plan.structure["name"] == "legacy_r20_parallel_draft_contract_join"
            else self.candidate_source
        )
        path = round_dir / "artifact" / "final-output.json"
        atomic_json(path, {"files": {"engine.py": source}})
        return {"artifact_path": str(path), "payload": read_json(path)}, [
            {
                "call_id": "builder",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 40,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 7,
                    "model_calls": 1,
                },
            }
        ]


class FakeEvaluator:
    def __init__(self, elo_by_source: dict[str, float]) -> None:
        self.elo_by_source = elo_by_source
        self.task = "build a legal chess engine"

    def evaluate(self, artifact_path: Path, *, evaluation_dir: Path) -> dict[str, Any]:
        source = read_json(artifact_path)["files"]["engine.py"]
        elo = self.elo_by_source[source]
        receipt = evaluation_dir / "benchmark-result-receipt.json"
        atomic_json(receipt, {"fake": True})
        result = {
            "valid": True,
            "failure_kind": None,
            "score_rate": 0.4,
            "wins": 10,
            "draws": 60,
            "losses": 30,
            "elo": elo,
            "elo_error_95": 100.0,
            "los": 0.5,
            "valid_games": 100,
            "candidate_failures": 0,
            "benchmark_receipt_path": str(receipt),
            "source_benchmark_receipt_path": str(receipt),
        }
        atomic_json(evaluation_dir / "evaluation.json", result)
        return result


class RetryFirstIncumbentEvaluator(FakeEvaluator):
    def __init__(self, elo_by_source: dict[str, float], incumbent_source: str) -> None:
        super().__init__(elo_by_source)
        self.incumbent_source = incumbent_source
        self.incumbent_calls = 0

    def evaluate(self, artifact_path: Path, *, evaluation_dir: Path) -> dict[str, Any]:
        source = read_json(artifact_path)["files"]["engine.py"]
        if source == self.incumbent_source:
            self.incumbent_calls += 1
            if self.incumbent_calls == 1:
                result = {
                    "valid": False,
                    "failure_kind": "benchmark_contract_failure:valid_games=100,candidate_failures=1",
                    "elo": None,
                    "valid_games": 100,
                    "candidate_failures": 1,
                }
                atomic_json(evaluation_dir / "evaluation.json", result)
                return result
        return super().evaluate(artifact_path, evaluation_dir=evaluation_dir)


def test_plan_enforces_one_causal_change_and_counter_fields() -> None:
    valid = LoopPlan.from_payload(_plan(), expected_mode="general")
    assert valid.structure_id.startswith("loop_")
    invalid = _plan()
    invalid["hypothesis"]["causal_change"]["change_count"] = 2
    with pytest.raises(PlanValidationError):
        LoopPlan.from_payload(invalid, expected_mode="general")
    with pytest.raises(PlanValidationError):
        LoopPlan.from_payload(_plan(), expected_mode="counter_hypothesis")
    counter = LoopPlan.from_payload(
        _plan(mode="counter_hypothesis"), expected_mode="counter_hypothesis"
    )
    assert counter.payload["proposal_mode"] == "counter_hypothesis"
    with pytest.raises(PlanValidationError):
        LoopPlan.from_payload(_plan(), expected_mode="emergent_exploration")
    emergent = LoopPlan.from_payload(
        _plan(mode="emergent_exploration"), expected_mode="emergent_exploration"
    )
    assert emergent.hypothesis["emergent_capability"]["capability_family"]


def test_second_emergent_attempt_requires_a_distinct_capability_family() -> None:
    plan = LoopPlan.from_payload(
        _plan(mode="emergent_exploration"), expected_mode="emergent_exploration"
    )
    capsule = {
        "search_control": {
            "emergent_capability_families_already_tested": [
                "evidence-triggered-replanning"
            ]
        }
    }
    with pytest.raises(PlanValidationError):
        plan.validate_search_context(capsule)


def test_architect_retries_invalid_plan_and_accounts_for_rejected_spend(tmp_path: Path) -> None:
    invalid = _plan()
    invalid["structure"]["stages"][0]["calls"][0]["inputs"].append("future_output")
    client = SequenceProposalClient([invalid, _plan()])
    architect = Architect(client)  # type: ignore[arg-type]
    capsule = {
        "search_control": {
            "proposal_mode": "general",
            "proposal_validation_max_attempts": 2,
        }
    }
    round_dir = tmp_path / "workspace" / "rounds" / "r0001"
    plan = architect.propose(capsule=capsule, round_dir=round_dir)
    assert plan.proposal_mode == "general"
    assert client.calls == 2
    assert (
        round_dir
        / "generation"
        / "attempts"
        / "attempt-01"
        / "validation-error.txt"
    ).is_file()

    pipeline = EvolutionPipeline(_fixture_config(tmp_path / "fixture"))
    ledger = pipeline._write_round_token_accounting(round_dir=round_dir, pairs=[])
    assert ledger["proposal_sol_xhigh"]["model_calls"] == 2
    assert ledger["proposal_invalid_spend"]["model_calls"] == 1
    assert ledger["proposal_sol_xhigh"]["effective_tokens"] == 26


def test_plan_normalizes_prior_call_output_alias() -> None:
    payload = _plan(organization="collaboration")
    payload["structure"]["stages"][1]["calls"][0]["inputs"][-1] = "critic.output"
    plan = LoopPlan.from_payload(payload, expected_mode="general")
    assert plan.structure["stages"][1]["calls"][0]["inputs"][-1] == "critic"


def _evaluation(elo: float | None) -> dict[str, Any]:
    return {"valid": elo is not None, "elo": elo}


def test_batch_uses_pair_majority_and_median_candidate() -> None:
    pairs = [
        {
            "incumbent_evaluation": _evaluation(-100.0),
            "candidate_evaluation": _evaluation(-80.0),
        },
        {
            "incumbent_evaluation": _evaluation(-95.0),
            "candidate_evaluation": _evaluation(-70.0),
        },
        {
            "incumbent_evaluation": _evaluation(-90.0),
            "candidate_evaluation": _evaluation(-85.0),
        },
    ]
    batch = judge_batch(pairs=pairs, anchor_elo=-94.211)
    assert batch["promoted"] is True
    assert batch["candidate_wins"] == 3
    assert batch["candidate_median_elo"] == -80.0
    assert batch["representative_candidate_pair"] == 1


def test_batch_rejects_invalid_incumbent_pair_instead_of_granting_free_win() -> None:
    pairs = [
        {
            "incumbent_evaluation": _evaluation(-261.806),
            "candidate_evaluation": _evaluation(-173.129),
        },
        {
            "incumbent_evaluation": {"valid": False, "elo": None},
            "candidate_evaluation": _evaluation(-132.041),
        },
        {
            "incumbent_evaluation": _evaluation(-135.979),
            "candidate_evaluation": _evaluation(-256.130),
        },
    ]
    batch = judge_batch(pairs=pairs, anchor_elo=-94.211)
    assert batch["promoted"] is False
    assert batch["inconclusive"] is True
    assert batch["invalid_pair_count"] == 1
    assert batch["candidate_wins"] == 1
    assert batch["candidate_losses"] == 1
    assert batch["representative_candidate_elo"] == -173.129
    assert batch["promotion_checks"]["incumbent_invalid_count_zero"] is False


def test_early_rejection_matches_ecr_impossibility_rule() -> None:
    verdicts = [
        pair_verdict(_evaluation(-90.0), _evaluation(-100.0)),
        pair_verdict(_evaluation(-90.0), _evaluation(-90.0)),
    ]
    assert rejection_is_irreversible(verdicts) is True


def test_candidate_failures_make_pair_ineligible() -> None:
    incumbent = {"valid": True, "elo": -200.0, "valid_games": 100, "candidate_failures": 0}
    candidate = {"valid": True, "elo": -100.0, "valid_games": 100, "candidate_failures": 1}
    assert pair_verdict(incumbent, candidate).verdict == "invalid"


def test_incumbent_failures_make_pair_ineligible() -> None:
    incumbent = {"valid": False, "elo": None, "valid_games": 100, "candidate_failures": 1}
    candidate = {"valid": True, "elo": -100.0, "valid_games": 100, "candidate_failures": 0}
    assert pair_verdict(incumbent, candidate).verdict == "invalid"


def test_three_pair_batch_promotes_structure_and_median_engine_together(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    pipeline = EvolutionPipeline(
        config,
        architect=FakeArchitect(_plan()),
        executor=FakeExecutor(
            incumbent_source="print('incumbent-rollout')\n",
            candidate_source="print('candidate')\n",
        ),
        evaluator=FakeEvaluator(
            {
                "print('incumbent-rollout')\n": -100.0,
                "print('candidate')\n": -80.0,
            }
        ),
    )
    before = pipeline.initialize()["champion"]
    summary = pipeline.run_round()
    after = pipeline.store.load()["champion"]
    assert summary["promoted"] is True
    assert after["package_id"] != before["package_id"]
    assert after["loop_structure"]["structure_id"] == summary["candidate_structure_id"]
    assert after["metrics"]["elo"] == -80.0
    assert summary["batch_decision"]["completed_pair_count"] == 3
    assert summary["batch_decision"]["candidate_wins"] == 3
    assert summary["batch_decision"]["anchor_panel"][0]["role"] == "current_champion"
    assert summary["batch_decision"]["anchor_panel"][1]["role"] == "frozen_lineage_baseline"
    assert summary["token_usage"]["internal_loop_luna_high"]["combined"]["model_calls"] == 6
    assert summary["token_usage"]["internal_loop_luna_high"]["combined"]["total_tokens"] == 720
    assert summary["token_usage"]["internal_loop_luna_high"]["combined"]["effective_tokens"] == 480
    assert Path(summary["token_accounting_path"]).is_file()
    assert "candidate" in Path(after["engine"]["artifact_path"]).read_text(encoding="utf-8")


def test_token_accounting_does_not_double_count_reasoning_and_keeps_retry_spend() -> None:
    one = normalize_usage(
        {
            "input_tokens": 100,
            "cached_input_tokens": 25,
            "output_tokens": 40,
            "reasoning_output_tokens": 30,
            "model_calls": 1,
        }
    )
    assert one["total_tokens"] == 140
    assert one["effective_tokens"] == 115
    attempt = {
        "execution_traces": {
            "incumbent": [{"usage": one}],
            "candidate": [{"usage": one}],
        }
    }
    ledger = pair_usage([attempt, attempt], accepted=True)
    assert ledger["all_attempts"]["combined"]["total_tokens"] == 560
    assert ledger["invalid_attempts"]["count"] == 1
    assert ledger["invalid_attempts"]["combined"]["total_tokens"] == 280


def test_interrupted_partial_attempt_recovers_completed_call_usage(tmp_path: Path) -> None:
    pipeline = EvolutionPipeline(_fixture_config(tmp_path))
    pipeline.initialize()
    attempt = tmp_path / "workspace" / "rounds" / "r0001" / "pairs" / "pair-01" / "attempts" / "attempt-01"
    receipt = attempt / "candidate" / "execution" / "calls" / "01-builder.receipt.json"
    atomic_json(
        receipt,
        {
            "call_id": "builder",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 25,
                "output_tokens": 40,
                "reasoning_output_tokens": 20,
                "model_calls": 1,
            },
        },
    )
    recovered = pipeline._recover_interrupted_attempt(attempt)
    assert recovered is not None
    assert recovered["candidate"]["evaluation"]["failure_kind"] == "interrupted_partial_arm"
    assert recovered["candidate"]["execution_traces"][0]["usage"]["input_tokens"] == 100
    assert recovered["incumbent"]["evaluation"]["valid"] is False


def test_abort_next_round_archives_partial_without_advancing_state(tmp_path: Path) -> None:
    pipeline = EvolutionPipeline(_fixture_config(tmp_path))
    before = pipeline.initialize()
    partial = tmp_path / "workspace" / "rounds" / "r0001"
    atomic_json(partial / "generation" / "partial.json", {"incomplete": True})
    result = pipeline.abort_next_round("test cancellation")
    after = pipeline.store.load()
    assert result["event"] == "incomplete_round_aborted"
    assert result["adjudicated"] is False
    assert Path(result["archive_path"]).is_dir()
    assert not partial.exists()
    assert after["round_index"] == before["round_index"]
    assert after["champion"]["package_id"] == before["champion"]["package_id"]


def test_invalid_pair_reruns_both_arms_before_counting_result(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    incumbent_source = "print('incumbent-rollout')\n"
    candidate_source = "print('candidate')\n"
    pipeline = EvolutionPipeline(
        config,
        architect=FakeArchitect(_plan()),
        executor=FakeExecutor(
            incumbent_source=incumbent_source,
            candidate_source=candidate_source,
        ),
        evaluator=RetryFirstIncumbentEvaluator(
            {incumbent_source: -100.0, candidate_source: -80.0},
            incumbent_source,
        ),
    )
    pipeline.initialize()
    summary = pipeline.run_round()
    pair_one = read_json(
        tmp_path
        / "workspace"
        / "rounds"
        / "r0001"
        / "pairs"
        / "pair-01"
        / "pair-summary.json"
    )
    assert summary["promoted"] is True
    assert pair_one["attempts_used"] == 2
    assert pair_one["invalid_attempts_exhausted"] is False
    assert len(pair_one["attempt_summary_paths"]) == 2


def test_fixed_round_uses_archived_plan_without_architect_call(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    plan_path = tmp_path / "fixed-plan.json"
    atomic_json(plan_path, _plan())
    incumbent_source = "print('incumbent-rollout')\n"
    candidate_source = "print('candidate')\n"
    pipeline = EvolutionPipeline(
        config,
        executor=FakeExecutor(
            incumbent_source=incumbent_source,
            candidate_source=candidate_source,
        ),
        evaluator=FakeEvaluator(
            {incumbent_source: -100.0, candidate_source: -80.0}
        ),
    )
    pipeline.initialize()
    summary = pipeline.run_fixed_round(plan_path)
    assert summary["event"] == "fixed_challenger_requalification_completed"
    assert summary["promoted"] is True


def test_search_cycle_counts_promoted_local_rounds_then_escalates(tmp_path: Path) -> None:
    config = _fixture_config(tmp_path)
    pipeline = EvolutionPipeline(config)
    initial = pipeline.initialize()["champion"]
    state = pipeline.store.load()

    def apply(round_index: int, *, promoted: bool) -> None:
        nonlocal state
        mode = state["proposal_mode"]
        plan = LoopPlan.from_payload(_plan(mode=mode), expected_mode=mode)
        batch = {
            "completed_pair_count": 3,
            "candidate_wins": 2 if promoted else 0,
            "candidate_losses": 0 if promoted else 3,
            "ties": 1 if promoted else 0,
            "candidate_median_elo": -80.0 if promoted else -100.0,
            "incumbent_median_elo": -90.0,
            "anchor_elo": -94.211,
            "median_delta": 10.0 if promoted else -10.0,
            "representative_candidate_elo": -80.0 if promoted else -100.0,
            "candidate_invalid_count": 0,
            "promotion_checks": {},
        }
        state = pipeline.store.apply_batch_outcome(
            state=state,
            round_index=round_index,
            plan=plan.payload,
            batch=batch,
            promoted_package=state["champion"] if promoted else None,
        )

    apply(1, promoted=True)
    assert state["proposal_mode"] == "general"
    assert state["local_refinement_count"] == 1

    apply(2, promoted=False)
    assert state["proposal_mode"] == "emergent_exploration"
    assert state["local_refinement_count"] == 2

    apply(3, promoted=False)
    assert state["proposal_mode"] == "emergent_exploration"
    assert state["emergent_failure_count"] == 1

    apply(4, promoted=False)
    assert state["proposal_mode"] == "counter_hypothesis"
    assert state["emergent_failure_count"] == 2

    apply(5, promoted=False)
    assert state["proposal_mode"] == "counter_hypothesis"

    apply(6, promoted=True)
    capsule = read_json(pipeline.store.capsule_path)
    assert state["champion"]["package_id"] == initial["package_id"]
    assert state["proposal_mode"] == "general"
    assert state["local_refinement_count"] == 0
    assert state["emergent_failure_count"] == 0
    assert len(capsule["recent_outcomes"]) == 3
    assert len(capsule["hypothesis_frontier"]) == 2
    assert len(capsule["conditional_lessons"]) == 3
    assert capsule["serialized_characters"] < 9000

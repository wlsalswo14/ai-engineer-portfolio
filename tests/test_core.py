from __future__ import annotations

import json
from pathlib import Path

import pytest

from primus.errors import ContractError, LifecycleError
from primus.models import ArmResult, LoopCall, LoopStructure, RoundStatus, Usage
from primus.outer import PublicFeedbackCompiler, generic_control
from primus.stats import judge_paired
from primus.store import PrimusStore


def structure() -> dict:
    return LoopStructure(
        name="test",
        organization="sequential",
        information_flow="one call",
        calls=(LoopCall("emit", "producer", "emit", ("task",), "answer"),),
        final_call_id="emit",
    ).to_dict()


def test_structure_identity_is_deterministic() -> None:
    first = LoopStructure.from_dict(structure())
    second = LoopStructure.from_dict(structure())
    assert first.structure_id == second.structure_id
    first.validate(max_calls=1)


def test_unknown_call_input_fails_closed() -> None:
    value = structure()
    value["calls"][0]["inputs"] = ["hidden_score"]
    with pytest.raises(ContractError):
        LoopStructure.from_dict(value).validate(max_calls=2)


def test_one_active_champion_and_atomic_promotion(tmp_path: Path) -> None:
    store = PrimusStore(tmp_path)
    store.initialize()
    store.import_champion(domain="chess", champion_id="a", structure=structure(), artifact=b"{}", active=True, source={})
    with pytest.raises(LifecycleError):
        store.import_champion(domain="chess", champion_id="b", structure=structure(), artifact=b"{}", active=True, source={})
    round_record = store.create_round("chess")
    with pytest.raises(LifecycleError):
        store.promote(run_id=round_record["run_id"], new_champion_id="b", structure=structure(), artifact=b"{}", certification_receipt_sha256="x", decision_sha256="y")
    store.transition(round_record["run_id"], RoundStatus.PLANNED)
    store.transition(round_record["run_id"], RoundStatus.GENERATED_DEV)
    store.transition(round_record["run_id"], RoundStatus.PUBLIC_EVALUATED)
    store.transition(round_record["run_id"], RoundStatus.PROVISIONAL)
    store.transition(round_record["run_id"], RoundStatus.GENERATED_CERT)
    store.transition(round_record["run_id"], RoundStatus.HIDDEN_EVALUATED)
    store.transition(round_record["run_id"], RoundStatus.CERTIFIED)
    promoted = store.promote(run_id=round_record["run_id"], new_champion_id="b", structure=structure(), artifact=b"{}", certification_receipt_sha256="x", decision_sha256="y")
    assert promoted["champion_id"] == "b"
    assert len([x for x in store.list_champions("chess") if x["status"] == "active"]) == 1


def test_certification_taskset_is_one_time(tmp_path: Path) -> None:
    store = PrimusStore(tmp_path)
    store.initialize()
    store.consume_taskset(taskset_sha256="a", domain="cache", split="certification", run_id="r1")
    store.consume_taskset(taskset_sha256="a", domain="cache", split="certification", run_id="r1")
    with pytest.raises(LifecycleError):
        store.consume_taskset(taskset_sha256="a", domain="cache", split="certification", run_id="r2")


def test_receipts_are_chained_and_auditable(tmp_path: Path) -> None:
    store = PrimusStore(tmp_path)
    store.initialize()
    store.append_receipt(domain="cache", run_id="r1", kind="a", payload={"x": 1})
    store.append_receipt(domain="cache", run_id="r1", kind="b", payload={"x": 2})
    assert "receipt-chain:2" in store.audit()


def test_hidden_evidence_cannot_become_public_feedback() -> None:
    with pytest.raises(ContractError):
        PublicFeedbackCompiler.compile(domain="chess", public_receipt={"split": "certification", "hidden": True})


def test_public_feedback_is_behavioral_not_numeric() -> None:
    feedback = PublicFeedbackCompiler.compile(
        domain="cache",
        public_receipt={
            "split": "development",
            "hidden": False,
            "results": [{"failure_class": "timeout", "public_bad_behavior": "slow", "public_required_behavior": "bounded", "public_check": "clock"}],
        },
    )
    assert feedback["public_only"] is True
    assert feedback["audit_examples"][0]["bad_behavior"] == "slow"


def _arm(name: str, replicate: int, score: float, *, valid: bool = True, cost: int = 10) -> ArmResult:
    return ArmResult(name, replicate, valid, score if valid else None, "a", "s", Usage(input_tokens=cost, model_calls=1))


def test_paired_majority_and_confidence_gate() -> None:
    incumbent = [_arm("incumbent", i, 0.0) for i in range(1, 6)]
    candidate = [_arm("candidate", i, 1.0) for i in range(1, 6)]
    result = judge_paired(incumbent=incumbent, candidate=candidate, minimum_effect=.5, confidence=.9, bootstrap_samples=1000, seed="x", require_confidence=True)
    assert result.passed and result.wins == 5 and result.lower_confidence_delta > 0


def test_invalid_candidate_fails_even_with_high_scores() -> None:
    incumbent = [_arm("incumbent", i, 0.0) for i in range(1, 4)]
    candidate = [_arm("candidate", 1, 100.0, valid=False), _arm("candidate", 2, 10.0), _arm("candidate", 3, 10.0)]
    result = judge_paired(incumbent=incumbent, candidate=candidate, minimum_effect=0, confidence=.9, bootstrap_samples=100, seed="x", require_confidence=False)
    assert not result.passed and "candidate_invalid" in result.reasons


def test_equal_budget_control_matches_call_count() -> None:
    control = generic_control(4, "engine")
    control.validate(max_calls=4)
    assert len(control.calls) == 4 and control.calls[-1].output_type == "engine"

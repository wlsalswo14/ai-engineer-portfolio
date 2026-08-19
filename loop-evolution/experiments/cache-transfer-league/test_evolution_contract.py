from __future__ import annotations

import hashlib
import json
from pathlib import Path

import run_evolution


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE / "workspace"
MODEL_CALLS = WORKSPACE / "model-calls"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def completed_rounds() -> list[int]:
    return [number for number in range(2, 101) if (WORKSPACE / "rounds" / f"R{number}" / "round-decision.json").is_file()]


def test_continuation_contract_and_authoritative_r1_are_immutable():
    contract = read_json(HERE / "EVOLUTION-R2-R5-CONTRACT.json")
    assert contract["authorized_display_rounds"] == [2, 3, 4, 5]
    assert contract["stop_after_display_round"] == 5
    assert contract["cache_r6_permitted"] is False
    assert sha256(WORKSPACE / "rounds" / "R1" / "R1-ATOMIC-COMMIT.json") == contract["authoritative_start"]["atomic_state_sha256"]
    assert sha256(WORKSPACE / "champion-r1" / "policy.py") == contract["authoritative_start"]["champion_policy_sha256"]
    assert sha256(WORKSPACE / "champion-r1" / "structure.json") == contract["authoritative_start"]["champion_structure_sha256"]

    r6_contract = read_json(HERE / "EVOLUTION-R6-R11-CONTRACT.json")
    assert r6_contract["authorized_display_rounds"] == [6, 7, 8, 9, 10, 11]
    assert r6_contract["stop_after_display_round"] == 11
    assert r6_contract["cache_r12_permitted"] is False
    assert sha256(WORKSPACE / "rounds" / "R5" / "R5-ATOMIC-COMMIT.json") == r6_contract["authoritative_start"]["atomic_state_sha256"]
    assert sha256(WORKSPACE / "rounds" / "R5" / "state.json") == r6_contract["authoritative_start"]["state_sha256"]
    assert sha256(WORKSPACE / "champion-r5" / "policy.py") == r6_contract["authoritative_start"]["champion_policy_sha256"]
    assert sha256(WORKSPACE / "champion-r5" / "structure.json") == r6_contract["authoritative_start"]["champion_structure_sha256"]
    assert sha256(WORKSPACE / "champion-r5" / "selection-receipt.json") == r6_contract["authoritative_start"]["selection_receipt_sha256"]
    epoch = read_json(HERE / "LUNA-FAST-EXECUTOR-EPOCH.json")
    assert epoch["authorized_display_rounds"] == [6, 7, 8, 9, 10, 11]
    assert epoch["executor_epoch_id"] == "luna-fast-priority-e1"
    assert sha256(HERE / "EVOLUTION-R6-R11-CONTRACT.json") == epoch["superseded_contract_binding"]["sha256"]
    assert (epoch["effective_inner_model_boundary"]["model"], epoch["effective_inner_model_boundary"]["reasoning_effort"], epoch["effective_inner_model_boundary"]["service_tier"], epoch["effective_inner_model_boundary"]["request_tier"]) == ("gpt-5.6-luna", "high", "fast", "priority")

    extension = read_json(HERE / "EVOLUTION-R9-R100-AMENDMENT.json")
    assert extension["authorized_display_round_range"] == {"start": 9, "end": 100}
    assert extension["stop_after_display_round"] == 100
    assert extension["cache_r101_permitted"] is False
    preserved = {row["path"]: row["sha256"] for row in extension["preserved_immutable_contracts"]}
    assert sha256(HERE / "EVOLUTION-R6-R11-CONTRACT.json") == preserved["EVOLUTION-R6-R11-CONTRACT.json"]
    assert sha256(HERE / "LUNA-FAST-EXECUTOR-EPOCH.json") == preserved["LUNA-FAST-EXECUTOR-EPOCH.json"]
    assert sha256(WORKSPACE / "rounds" / "R8" / "R8-ATOMIC-COMMIT.json") == extension["authoritative_start"]["atomic_state_sha256"]
    assert sha256(WORKSPACE / "rounds" / "R8" / "state.json") == extension["authoritative_start"]["state_sha256"]
    assert sha256(WORKSPACE / "champion-r8" / "policy.py") == extension["authoritative_start"]["champion_policy_sha256"]
    assert sha256(WORKSPACE / "champion-r8" / "structure.json") == extension["authoritative_start"]["champion_structure_sha256"]

    stop = read_json(HERE / "STOP-AFTER-R96-AMENDMENT.json")
    assert stop["amendment_id"] == "cache-stop-after-active-display-r96"
    assert stop["stop_after_display_round"] == 96
    assert stop["cache_r97_permitted"] is False
    assert sha256(WORKSPACE / "rounds" / "R95" / "R95-ATOMIC-COMMIT.json") == stop["authoritative_start"]["atomic_state_sha256"]
    assert sha256(WORKSPACE / "rounds" / "R95" / "state.json") == stop["authoritative_start"]["state_sha256"]
    assert sha256(WORKSPACE / "champion-r95" / "policy.py") == stop["authoritative_start"]["champion_policy_sha256"]
    assert sha256(WORKSPACE / "champion-r95" / "structure.json") == stop["authoritative_start"]["champion_structure_sha256"]
    assert stop["validity_semantics"]["preseal_generic_validity"] == "diagnostic only"
    assert run_evolution.AUTHORIZED_ROUNDS[-1] == 96
    assert 97 not in run_evolution.AUTHORIZED_ROUNDS


def test_each_completed_round_has_one_sol_and_only_luna_inner_roles():
    assert completed_rounds()
    for number in completed_rounds():
        tag = f"R{number}"
        round_dir = WORKSPACE / "rounds" / tag
        seal = read_json(round_dir / "pre-evaluation-seal.json")
        architect = read_json(MODEL_CALLS / f"{tag}-structure-architect" / "final-receipt.json")
        assert (architect["model"], architect["reasoning_effort"], architect["service_tier"], architect["request_tier"], architect["tools_used"]) == ("gpt-5.6-sol", "max", "fast", "priority", [])
        assert seal["architect"]["calls"] == 1
        inner_count = 0
        for entry in seal["entries"]:
            arm_seal = read_json(HERE / entry["seal_path"])
            for receipt_ref in arm_seal["model_receipts"]:
                receipt = read_json(HERE / receipt_ref["path"])
                expected_tiers = ("fast", "priority") if number >= 6 else ("default", "default")
                assert (receipt["model"], receipt["reasoning_effort"], receipt["service_tier"], receipt["request_tier"], receipt["tools_used"]) == ("gpt-5.6-luna", "high", *expected_tiers, [])
                inner_count += 1
        assert inner_count == seal["inner_roles"]["calls"]


def test_r6_pre_fast_executor_epoch_is_quarantined_and_ineligible():
    epoch = read_json(HERE / "LUNA-FAST-EXECUTOR-EPOCH.json")
    ref = epoch["r6_restart_binding"]["quarantine_manifest"]
    quarantine = read_json(HERE / ref["path"])
    assert sha256(HERE / ref["path"]) == ref["sha256"]
    assert quarantine["status"] == "aborted-pre-luna-fast-policy"
    assert quarantine["completed_default_tier_receipts"] == 7
    assert len(quarantine["interrupted_without_final_receipt"]) == 1
    assert quarantine["generated_arm_artifacts"] == 5
    assert quarantine["seal_eligibility"] is False
    assert quarantine["score_eligibility"] is False
    assert quarantine["selection_eligibility"] is False
    assert quarantine["not_best_of_n"] is True


def test_policy_capsule_output_kind_preserves_raw_architect_topology():
    proposal_path = WORKSPACE / "rounds" / "R6" / "architect" / "proposal.json"
    if not proposal_path.is_file():
        return
    proposal = read_json(proposal_path)
    policy_kinds = proposal["validation"].get("policy_bearing_output_kinds", [])
    if policy_kinds:
        assert proposal["validation"].get("output_type_normalizations", []) == []
        assert policy_kinds == [
            {
                "call_id": "originate_obligation_capsule",
                "output_type": "policy_capsule",
                "executor_semantics": "complete policy artifact plus obligation evidence on the same single lineage",
            }
        ]
        assert proposal["architect_response"]["candidate_structure"]["stages"][0]["calls"][0]["output_type"] == "policy_capsule"
        proposed = read_json(WORKSPACE / "rounds" / "R6" / "architect" / "proposed-structure.json")
        assert proposed["stages"][0]["calls"][0]["output_type"] == "policy_capsule"


def test_coarse_graph_collision_requires_and_records_novel_edge_semantics():
    parsed_path = MODEL_CALLS / "R7-structure-architect" / "parsed-response.json"
    receipt_path = MODEL_CALLS / "R7-structure-architect" / "final-receipt.json"
    prompt_path = MODEL_CALLS / "R7-structure-architect" / "prompt.txt"
    if not (parsed_path.is_file() and receipt_path.is_file() and prompt_path.is_file()):
        return
    runner = run_evolution.RoundRunner(7)
    audit = runner.validate_architect_response(
        read_json(parsed_path),
        prompt_path.read_text(encoding="utf-8"),
        read_json(receipt_path),
    )
    collision = audit["coarse_topology_collision_override"]
    assert collision is not None
    assert collision["mere_role_fission_or_rename"] is False
    assert audit["semantic_topology_fingerprint"] not in run_evolution.prior_semantic_topology_fingerprints(7)


def test_notebook_semantic_fingerprints_are_backward_compatible_with_r1_schema():
    notebook = run_evolution.build_error_notebook(2)
    legacy_rows = [row for row in notebook["factor_frontier"] if row["semantic_topology_fingerprint"] is None]
    assert legacy_rows
    assert all("semantic_topology_fingerprint" in row for row in notebook["factor_frontier"])


def test_executable_policy_state_is_a_first_class_policy_bearing_intermediate():
    parsed_path = MODEL_CALLS / "R12-structure-architect" / "parsed-response.json"
    receipt_path = MODEL_CALLS / "R12-structure-architect" / "final-receipt.json"
    prompt_path = MODEL_CALLS / "R12-structure-architect" / "prompt.txt"
    if not (parsed_path.is_file() and receipt_path.is_file() and prompt_path.is_file()):
        return
    runner = run_evolution.RoundRunner(12)
    parsed = read_json(parsed_path)
    audit = runner.validate_architect_response(
        parsed,
        prompt_path.read_text(encoding="utf-8"),
        read_json(receipt_path),
    )
    assert audit["output_type_normalizations"] == []
    assert audit["policy_bearing_output_kinds"] == [
        {
            "call_id": "independent_genesis_materializer",
            "output_type": "executable_policy_state",
            "executor_semantics": "complete executable policy artifact serving as the sole constructive lineage state",
        }
    ]
    assert parsed["candidate_structure"]["stages"][0]["calls"][0]["output_type"] == "executable_policy_state"


def test_display_r20_accounting_does_not_capture_bootstrap_r20_rep_receipts():
    seal = WORKSPACE / "rounds" / "R20" / "pre-evaluation-seal.json"
    if not seal.is_file():
        return
    paths, receipts = run_evolution.RoundRunner(20).round_receipts()
    assert len(paths) == 10
    assert len(receipts) == 10
    assert sum(row["call_id"] == "R20-structure-architect" for row in receipts) == 1
    assert all("-rep" not in row["call_id"] for row in receipts)


def test_executable_policy_closure_preserves_r24_raw_topology():
    parsed_path = MODEL_CALLS / "R24-structure-architect" / "parsed-response.json"
    receipt_path = MODEL_CALLS / "R24-structure-architect" / "final-receipt.json"
    prompt_path = MODEL_CALLS / "R24-structure-architect" / "prompt.txt"
    if not (parsed_path.is_file() and receipt_path.is_file() and prompt_path.is_file()):
        return
    runner = run_evolution.RoundRunner(24)
    parsed = read_json(parsed_path)
    audit = runner.validate_architect_response(parsed, prompt_path.read_text(encoding="utf-8"), read_json(receipt_path))
    assert audit["output_type_normalizations"] == []
    assert audit["policy_bearing_output_kinds"] == [
        {
            "call_id": "form_executable_closure",
            "output_type": "executable_policy_closure",
            "executor_semantics": "self-contained executable policy artifact crossing a provenance-blind closure edge",
        }
    ]
    assert parsed["candidate_structure"]["stages"][0]["calls"][0]["output_type"] == "executable_policy_closure"


def test_analysis_role_policy_marker_is_sealed_as_invalid_without_retry_or_substitution():
    call_id = "R72-pair02-candidate-call01-map_provenance_obligations"
    call_dir = MODEL_CALLS / call_id
    parsed_path = call_dir / "parsed-response.json"
    receipt_path = call_dir / "final-receipt.json"
    if not (parsed_path.is_file() and receipt_path.is_file()):
        return

    parsed_sha = "49b0c10e7caa5e0e7c078b40314e9ac8ae8227227f1c69801b3cf4db914b3bb5"
    receipt_sha = "96ea20fad1cdc8c2c1e5f554e96d9ad428a07ea78b453a1f7dba907dea591246"
    assert sha256(parsed_path) == parsed_sha
    assert sha256(receipt_path) == receipt_sha
    violations = run_evolution.analysis_output_contract_violations(read_json(parsed_path))
    assert violations == ["analysis_role_emitted_policy_code"]

    manifest_path = WORKSPACE / "rounds" / "R72" / "pairs" / "pair-02" / "candidate" / "generation-manifest.json"
    if not manifest_path.is_file():
        return
    manifest = read_json(manifest_path)
    assert manifest["semantic_contract_valid"] is False
    assert manifest["semantic_violation_handling"] == "raw_output_preserved_no_retry_no_substitution"
    assert manifest["direct_substitution"] is False
    assert manifest["transport_retry_for_semantic_violation"] is False
    matching = [row for row in manifest["semantic_contract_violations"] if row["call_id"] == call_id]
    assert matching == [{"call_id": call_id, "reason": "analysis_role_emitted_policy_code", "role_id": "map_provenance_obligations"}]
    assert sha256(parsed_path) == parsed_sha
    assert sha256(receipt_path) == receipt_sha


def test_r87_transport_disconnect_has_one_same_prompt_resume_and_preserves_completed_calls():
    call_id = "R87-pair01-candidate-call01-originate_executable_capsule"
    call_dir = MODEL_CALLS / call_id
    raw_path = call_dir / "raw-events.jsonl"
    failure_path = call_dir / "failure-receipt.json"
    resume_path = call_dir / "transport-resume-manifest.json"
    receipt_path = call_dir / "final-receipt.json"

    assert sha256(raw_path) == "4c095ab785b49e02f0a68d44134432554e6ecf6cc2b16e8fb649db771b03c3ad"
    failure = read_json(failure_path)
    assert failure["call_id"] == call_id
    assert failure["failure_kind"] == "transport"
    assert failure["failure_stage"] == "jsonl_stream"
    assert failure["usage"] == {
        "cached_input_tokens": 19200,
        "input_tokens": 20915,
        "output_tokens": 1567,
        "reasoning_output_tokens": 0,
    }

    resume = read_json(resume_path)
    assert resume["call_id"] == call_id
    assert resume["same_call_id"] is True
    assert resume["same_prompt"] is True
    assert resume["bounded_max_attempts"] == 2
    assert resume["retry_attempt"] == 2
    assert resume["retry_directory"] == f"workspace\\model-calls\\{call_id}\\retry-02"
    assert resume["direct_substitution"] is False
    assert resume["semantic_failure"] is False
    assert resume["attempt_01"]["raw_events_sha256"] == sha256(raw_path)
    assert resume["attempt_01"]["failure_receipt_sha256"] == sha256(failure_path)
    assert resume["completed_calls_reused_without_reexecution"]
    for item in resume["completed_calls_reused_without_reexecution"]:
        assert sha256(HERE / item["receipt_path"]) == item["receipt_sha256"]
        assert sha256(HERE / item["result_path"]) == item["result_sha256"]

    receipt = read_json(receipt_path)
    assert receipt["call_id"] == call_id
    assert receipt["transport_retry"] is True
    assert receipt["prior_transport_failure_receipt"] == f"workspace\\model-calls\\{call_id}\\failure-receipt.json"
    assert receipt["raw_events_path"] == f"workspace\\model-calls\\{call_id}\\retry-02\\raw-events.jsonl"
    assert receipt["prompt_sha256"] == resume["prompt_sha256"]


def test_incumbent_coarse_shape_can_carry_a_novel_certified_edge_semantic():
    parsed_path = MODEL_CALLS / "R27-structure-architect" / "parsed-response.json"
    receipt_path = MODEL_CALLS / "R27-structure-architect" / "final-receipt.json"
    prompt_path = MODEL_CALLS / "R27-structure-architect" / "prompt.txt"
    if not (parsed_path.is_file() and receipt_path.is_file() and prompt_path.is_file()):
        return
    runner = run_evolution.RoundRunner(27)
    audit = runner.validate_architect_response(
        read_json(parsed_path),
        prompt_path.read_text(encoding="utf-8"),
        read_json(receipt_path),
    )
    collision = audit["coarse_topology_collision_override"]
    assert collision is not None
    assert collision["matches_incumbent_coarse_shape"] is True
    assert collision["mere_role_fission_or_rename"] is False
    assert audit["semantic_topology_fingerprint"] not in run_evolution.prior_semantic_topology_fingerprints(27)


def test_every_duel_has_six_sealed_common_anchor_arms_before_replay2():
    for number in completed_rounds():
        round_dir = WORKSPACE / "rounds" / f"R{number}"
        seal = read_json(round_dir / "pre-evaluation-seal.json")
        assert len(seal["entries"]) == 6
        assert seal["sealed_before_any_frozen_evaluation"] is True
        for entry in seal["entries"]:
            assert sha256(HERE / entry["artifact_path"]) == entry["artifact_sha256"]
            assert sha256(HERE / entry["seal_path"]) == entry["seal_sha256"]
            manifest = read_json(HERE / read_json(HERE / entry["seal_path"])["generation_manifest_path"])
            assert manifest["anchor_sha256"] == seal["common_inputs"]["anchor_policy_sha256"]
            assert manifest["hypothesis_sha256"] == seal["common_inputs"]["hypothesis_sha256"]
            assert manifest["official_numeric_scores_visible"] is False
            for replay in (1, 2):
                record = read_json(round_dir / "evaluation" / f"pair-{entry['pair']:02d}" / entry["arm"] / f"replay-{replay:02d}.json")
                assert record["artifact_sha256"] == entry["artifact_sha256"]
                assert record["started_at"] >= seal["sealed_at"]


def test_promotion_and_champion_decisions_recompute():
    for number in completed_rounds():
        round_dir = WORKSPACE / "rounds" / f"R{number}"
        batch = read_json(round_dir / "evaluation" / "evaluation-batch.json")
        selection = read_json(WORKSPACE / f"champion-r{number}" / "selection-receipt.json")
        candidate_wins = sum(row["verdict"] == "candidate_win" for row in batch["pairs"])
        incumbent_wins = sum(row["verdict"] == "incumbent_win" for row in batch["pairs"])
        all_valid = all(row[arm]["valid"] for row in batch["pairs"] for arm in ("incumbent", "candidate"))
        majority = candidate_wins >= 2 and candidate_wins > incumbent_wins
        strict_median = batch["aggregate"]["candidate_median"] > batch["aggregate"]["incumbent_median"]
        promoted = all_valid and majority and strict_median and batch["confirmation_passed"]
        assert batch["promotion_contract_passed"] is promoted
        assert selection["promoted"] is promoted
        assert sha256(WORKSPACE / f"champion-r{number}" / "policy.py") == selection["artifact_sha256"]
        assert sha256(WORKSPACE / f"champion-r{number}" / "structure.json") == selection["structure_sha256"]
        if not promoted:
            assert selection["artifact_sha256"] == sha256(WORKSPACE / f"champion-r{number - 1}" / "policy.py")
            assert selection["structure_sha256"] == sha256(WORKSPACE / f"champion-r{number - 1}" / "structure.json")


def test_state_machine_is_derived_and_authorized_continuations_preserve_checkpoints():
    rounds = completed_rounds()
    for number in rounds:
        state = read_json(WORKSPACE / "rounds" / f"R{number}" / "state.json")
        expected = run_evolution.search_after(state["search_control_before"], state["promoted"])
        assert state["search_control_after"] == expected
        guard_key = "cache_r6_opened" if number <= 5 else "cache_r12_opened" if number <= 8 else "cache_r97_opened" if number == 96 else "cache_r101_opened"
        assert state[guard_key] is False
        if number < max(rounds):
            next_state = read_json(WORKSPACE / "rounds" / f"R{number + 1}" / "state.json")
            assert next_state["search_control_before"]["proposal_mode"] == state["search_control_after"]["next_proposal_mode"]
    r6_round = WORKSPACE / "rounds" / "R6"
    if r6_round.exists():
        contract = read_json(HERE / "EVOLUTION-R6-R11-CONTRACT.json")
        assert sha256(WORKSPACE / "rounds" / "R5" / "R5-ATOMIC-COMMIT.json") == contract["authoritative_start"]["atomic_state_sha256"]
        assert read_json(r6_round / "source-manifest.json")["prior_atomic"]["sha256"] == contract["authoritative_start"]["atomic_state_sha256"]
    r9_round = WORKSPACE / "rounds" / "R9"
    if r9_round.exists():
        extension = read_json(HERE / "EVOLUTION-R9-R100-AMENDMENT.json")
        assert read_json(r9_round / "source-manifest.json")["prior_atomic"]["sha256"] == extension["authoritative_start"]["atomic_state_sha256"]
        assert read_json(r9_round / "source-manifest.json")["r100_extension_amendment"]["sha256"] == sha256(HERE / "EVOLUTION-R9-R100-AMENDMENT.json")
    assert not (WORKSPACE / "rounds" / "R101").exists()
    assert not (WORKSPACE / "champion-r101").exists()
    assert not (WORKSPACE / "rounds" / "R97").exists()
    assert not (WORKSPACE / "champion-r97").exists()

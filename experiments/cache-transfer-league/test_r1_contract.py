from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import run_r1


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE / "workspace"
ROUND = WORKSPACE / "rounds" / "R1"
MODEL_CALLS = WORKSPACE / "model-calls"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_predecessor_parser_accepts_immediate_edge_and_rejects_bypass():
    proposed = read_json(ROUND / "architect" / "proposed-structure.json")
    calls = run_r1.validate_structure(proposed)
    assert len(calls) == 2
    assert calls[0]["id"] in calls[1]["inputs"]

    bypass = copy.deepcopy(proposed)
    first, second = bypass["stages"][0]["calls"]
    middle = copy.deepcopy(second)
    middle["id"] = "middle_falsifier"
    middle["inputs"] = [first["id"]]
    middle["output_type"] = "analysis"
    second["inputs"] = [middle["id"], first["id"]]
    bypass["stages"][0]["calls"] = [first, middle, second]
    with pytest.raises(run_r1.base.CampaignError, match="bypasses"):
        run_r1.validate_structure(bypass)


def test_authoritative_r0_hashes_are_unchanged():
    assert sha256(WORKSPACE / "champion-r0" / "policy.py") == "294fb24343b8694d908efd6141fad01df3eb5543af329f7f473c0abbace03a60"
    assert sha256(WORKSPACE / "champion-r0" / "structure.json") == "1dc7dc0e89c5c5780a03e14734bfe4d2b56d039eb2967912b03fa2b209dffd4f"
    assert sha256(WORKSPACE / "champion-r0" / "selection-receipt.json") == "406d3c1f3db2f0b9246262919490d7e76b46fed60851305e22c0285a0e94b1f8"
    assert sha256(WORKSPACE / "R0-ATOMIC-COMMIT.json") == "c426f4e658ddcfcd77a17e8d56d14220ef845fa0004c94dc50b79ee4c3b65cce"


def test_one_sol_architect_and_exactly_nine_luna_inner_calls():
    seal = read_json(ROUND / "pre-evaluation-seal.json")
    assert seal["architect"]["calls"] == 1
    assert seal["inner_roles"]["calls"] == 9
    architect = read_json(MODEL_CALLS / "R1-structural-mutation-architect" / "final-receipt.json")
    assert (architect["model"], architect["reasoning_effort"]) == ("gpt-5.6-sol", "max")
    assert (architect["service_tier"], architect["request_tier"], architect["tools_used"]) == ("fast", "priority", [])

    inner_receipts = []
    for entry in seal["entries"]:
        arm_seal = read_json(HERE / entry["seal_path"])
        for item in arm_seal["model_receipts"]:
            receipt = read_json(HERE / item["path"])
            inner_receipts.append(receipt)
            assert (receipt["model"], receipt["reasoning_effort"]) == ("gpt-5.6-luna", "high")
            assert (receipt["service_tier"], receipt["request_tier"], receipt["tools_used"]) == ("default", "default", [])
    assert len(inner_receipts) == 9
    assert len({row["call_id"] for row in inner_receipts}) == 9


def test_six_arms_share_anchor_task_hypothesis_and_were_sealed_before_score():
    seal = read_json(ROUND / "pre-evaluation-seal.json")
    assert len(seal["entries"]) == 6
    assert seal["sealed_before_any_frozen_evaluation"] is True
    expected = seal["common_inputs"]
    for entry in seal["entries"]:
        assert sha256(HERE / entry["artifact_path"]) == entry["artifact_sha256"]
        assert sha256(HERE / entry["seal_path"]) == entry["seal_sha256"]
        arm_seal = read_json(HERE / entry["seal_path"])
        manifest = read_json(HERE / arm_seal["generation_manifest_path"])
        assert manifest["anchor_sha256"] == expected["anchor_policy_sha256"]
        assert manifest["task_sha256"] == expected["task_sha256"]
        assert manifest["hypothesis_sha256"] == expected["hypothesis_sha256"]
        assert manifest["official_scores_visible"] is False
        assert manifest["benchmark_fixtures_visible"] is False
        for replay in (1, 2):
            record = read_json(ROUND / "evaluation" / f"pair-{entry['pair']:02d}" / entry["arm"] / f"replay-{replay:02d}.json")
            assert record["started_at"] >= seal["sealed_at"]
            assert record["artifact_sha256"] == entry["artifact_sha256"]


def test_frozen_replay2_pair_and_promotion_contract_recompute():
    batch = read_json(ROUND / "evaluation" / "evaluation-batch.json")
    assert batch["benchmark"]["field"] == "cache_policy_scratch"
    assert batch["benchmark"]["seed"] == 20260605
    assert batch["benchmark"]["scale"] == 3
    assert batch["benchmark"]["trace_count"] == 9
    assert batch["benchmark"]["fixture_sha256"] == "793cbd7e5c04e896650ebc713fc29654fc63cf5fe1aaba15f6f6149d11795d87"
    assert batch["replay_count"] == 2
    assert len(batch["pairs"]) == 3
    candidate_wins = sum(row["verdict"] == "candidate_win" for row in batch["pairs"])
    incumbent_wins = sum(row["verdict"] == "incumbent_win" for row in batch["pairs"])
    all_valid = all(row[arm]["valid"] for row in batch["pairs"] for arm in ("incumbent", "candidate"))
    majority = candidate_wins >= 2 and candidate_wins > incumbent_wins
    strict_median = batch["aggregate"]["candidate_median"] > batch["aggregate"]["incumbent_median"]
    expected_promote = all_valid and majority and strict_median and batch["confirmation_passed"]
    assert batch["aggregate"]["candidate_wins"] == candidate_wins
    assert batch["aggregate"]["incumbent_wins"] == incumbent_wins
    assert batch["aggregate"]["candidate_pairwise_majority"] is majority
    assert batch["promotion_contract_passed"] is expected_promote


def test_champion_decision_and_stop_state_are_bound_to_authorized_continuation():
    batch = read_json(ROUND / "evaluation" / "evaluation-batch.json")
    selection = read_json(WORKSPACE / "champion-r1" / "selection-receipt.json")
    state = read_json(ROUND / "state.json")
    assert selection["promotion_contract_passed"] == batch["promotion_contract_passed"]
    assert sha256(WORKSPACE / "champion-r1" / "policy.py") == selection["artifact_sha256"]
    assert sha256(WORKSPACE / "champion-r1" / "structure.json") == selection["structure_sha256"]
    if not batch["promotion_contract_passed"]:
        assert selection["artifact_sha256"] == "294fb24343b8694d908efd6141fad01df3eb5543af329f7f473c0abbace03a60"
        assert selection["structure_sha256"] == "1dc7dc0e89c5c5780a03e14734bfe4d2b56d039eb2967912b03fa2b209dffd4f"
    assert state["display_round"] == 1
    assert state["status"] == "stopped-after-display-r1"
    assert state["cache_r2_opened"] is False
    assert state["next_round_permitted"] is False

    # R1 was originally committed as a terminal checkpoint.  A later user
    # authorization may extend that immutable checkpoint, but only through a
    # continuation contract that binds the exact R1 atomic state and champion.
    r2_round = WORKSPACE / "rounds" / "R2"
    if r2_round.exists():
        continuation = read_json(HERE / "EVOLUTION-R2-R5-CONTRACT.json")
        assert continuation["authorized_display_rounds"] == [2, 3, 4, 5]
        assert continuation["cache_r6_permitted"] is False
        assert sha256(WORKSPACE / "rounds" / "R1" / "R1-ATOMIC-COMMIT.json") == continuation["authoritative_start"]["atomic_state_sha256"]
        assert sha256(WORKSPACE / "champion-r1" / "policy.py") == continuation["authoritative_start"]["champion_policy_sha256"]
        assert sha256(WORKSPACE / "champion-r1" / "structure.json") == continuation["authoritative_start"]["champion_structure_sha256"]
        assert read_json(r2_round / "state.json")["display_round"] == 2
        assert (WORKSPACE / "champion-r2").is_dir()
    else:
        assert not (WORKSPACE / "champion-r2").exists()

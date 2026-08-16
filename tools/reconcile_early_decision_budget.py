from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loop_evolution.common import atomic_json, content_hash, read_json  # noqa: E402
from loop_evolution.pipeline import EvolutionPipeline  # noqa: E402


def reconcile(config_path: Path, round_index: int) -> dict[str, object]:
    pipeline = EvolutionPipeline(config_path.resolve())
    store = pipeline.store
    state = store.load()
    if int(state["round_index"]) != round_index:
        raise RuntimeError(
            f"can only reconcile the current committed round: state={state['round_index']}, requested={round_index}"
        )
    round_dir = pipeline.workspace / "rounds" / f"r{round_index:04d}"
    batch_path = round_dir / "evaluation" / "batch-decision.json"
    summary_path = round_dir / "round-summary.json"
    batch = read_json(batch_path)
    if not (
        bool(batch.get("irreversible_rejection_early_stop_applied"))
        and int(batch.get("completed_pair_count", 0)) >= 2
        and int(batch.get("candidate_invalid_count", 0)) == 0
        and int(batch.get("incumbent_invalid_count", 0)) == 0
    ):
        raise RuntimeError("round is not a clean irreversible early rejection")

    outcomes = [dict(item) for item in state["recent_outcomes"]]
    outcome_index = next(
        (index for index, item in enumerate(outcomes) if int(item.get("round", -1)) == round_index),
        None,
    )
    if outcome_index is None:
        raise RuntimeError("current round is absent from recent outcomes")
    outcome = outcomes[outcome_index]
    if bool(outcome.get("valid_batch_consumed_search_budget")):
        return {
            "reconciled": False,
            "already_counted": True,
            "round": round_index,
            "proposal_mode": state["proposal_mode"],
        }
    if str(outcome.get("failure_kind")) != "invalid_or_incomplete_batch_not_counted":
        raise RuntimeError("round does not carry the legacy uncounted disposition")

    savepoint_dir = pipeline.workspace / "savepoints"
    savepoint_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    savepoint_path = savepoint_dir / f"before-early-decision-budget-reconcile-r{round_index:04d}-{stamp}.json"
    atomic_json(
        savepoint_path,
        {
            "schema_version": 1,
            "reason": "count a clean irreversible two-pair rejection as a valid search-budget trial",
            "state": state,
            "state_sha256": content_hash(state),
            "batch_path": str(batch_path.resolve()),
            "batch_sha256": content_hash(batch),
        },
    )

    tested_mode = str(outcome["proposal_mode"])
    search_control = store.advance_search_control(
        state,
        tested_mode=tested_mode,
        promoted=False,
        batch_valid=True,
    )
    outcomes[outcome_index] = {
        **outcome,
        "valid_batch_consumed_search_budget": True,
        "irreversible_rejection_early_decision": True,
        "failure_kind": "matched_batch_did_not_satisfy_promotion",
    }
    frontier = [dict(item) for item in state["hypothesis_frontier"]]
    frontier_index = next(
        (index for index, item in enumerate(frontier) if int(item.get("round", -1)) == round_index),
        None,
    )
    if frontier_index is not None and frontier[frontier_index].get("status") == "invalid_or_incomplete":
        frontier[frontier_index] = {
            **frontier[frontier_index],
            "status": "not_supported_in_tested_conditions",
        }

    updated = {
        **state,
        **search_control,
        "recent_outcomes": outcomes,
        "hypothesis_frontier": frontier,
    }
    store.write_capsule(updated)
    store.save(updated)

    archive_sha = store.append_archive(
        {
            "event": "irreversible_early_rejection_budget_reconciled",
            "round": round_index,
            "completed_pair_count": int(batch["completed_pair_count"]),
            "candidate_wins": int(batch["candidate_wins"]),
            "candidate_losses": int(batch["candidate_losses"]),
            "savepoint_path": str(savepoint_path.resolve()),
            "state_sha256_after": content_hash(updated),
            "proposal_mode_after": updated["proposal_mode"],
        }
    )
    if summary_path.is_file():
        summary = read_json(summary_path)
        atomic_json(
            summary_path,
            {
                **summary,
                "stagnation_count_after": updated["stagnation_count"],
                "local_refinement_count_after": updated["local_refinement_count"],
                "emergent_failure_count_after": updated["emergent_failure_count"],
                "proposal_mode_after": updated["proposal_mode"],
                "search_budget_reconciliation": {
                    "reason": "clean irreversible early rejection counts as a valid trial",
                    "savepoint_path": str(savepoint_path.resolve()),
                    "archive_record_sha256": archive_sha,
                },
            },
        )
    return {
        "reconciled": True,
        "round": round_index,
        "savepoint_path": str(savepoint_path.resolve()),
        "archive_record_sha256": archive_sha,
        "local_refinement_count": updated["local_refinement_count"],
        "emergent_failure_count": updated["emergent_failure_count"],
        "proposal_mode": updated["proposal_mode"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--round", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.config, args.round), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

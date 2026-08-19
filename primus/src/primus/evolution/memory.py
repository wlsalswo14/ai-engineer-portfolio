from __future__ import annotations

from pathlib import Path
from typing import Any

from primus.errors import ContractError
from primus.jsonutil import content_hash, read_json


def compile_experiment_lesson(
    *,
    domain: str,
    run_id: str,
    proposal: dict[str, Any],
    public_receipt: dict[str, Any],
    public_decision: dict[str, Any],
) -> dict[str, Any]:
    """Turn a public match into score-free, reusable experimental memory."""
    if public_receipt.get("split") != "development" or public_receipt.get("hidden", False):
        raise ContractError("experiment memory accepts public development evidence only")

    indexed = {
        (str(item.get("arm")), int(item.get("replicate", 0))): item
        for item in public_receipt.get("results", [])
    }
    replicates = sorted({replicate for arm, replicate in indexed if arm == "candidate"})
    wins = losses = ties = invalid = 0
    failure_clusters: set[str] = set()
    candidate_cost = incumbent_cost = 0
    for replicate in replicates:
        incumbent = indexed.get(("incumbent", replicate))
        candidate = indexed.get(("candidate", replicate))
        if not candidate:
            continue
        candidate_cost += int(candidate.get("usage", {}).get("effective_tokens", 0))
        if incumbent:
            incumbent_cost += int(incumbent.get("usage", {}).get("effective_tokens", 0))
        failure = candidate.get("failure_class")
        if failure:
            failure_clusters.add(str(failure))
        if not candidate.get("valid") or candidate.get("score") is None:
            invalid += 1
            continue
        if not incumbent or not incumbent.get("valid") or incumbent.get("score") is None:
            wins += 1
            continue
        candidate_score = float(candidate["score"])
        incumbent_score = float(incumbent["score"])
        if candidate_score > incumbent_score:
            wins += 1
        elif candidate_score < incumbent_score:
            losses += 1
        else:
            ties += 1

    if invalid:
        quality_signal = "candidate_invalid"
    elif wins > losses:
        quality_signal = "mostly_improved"
    elif losses > wins:
        quality_signal = "mostly_regressed"
    else:
        quality_signal = "mixed_or_tied"
    if candidate_cost < incumbent_cost:
        cost_signal = "lower"
    elif candidate_cost > incumbent_cost:
        cost_signal = "higher"
    else:
        cost_signal = "same"

    decision_passed = bool(public_decision.get("passed"))
    lesson = {
        "schema_version": 1,
        "domain": domain,
        "run_id": run_id,
        "public_only": True,
        "operation": str(proposal.get("exploration_operation", "open")),
        "changed_factor": str(proposal.get("changed_factor", "")),
        "hypothesis": str(proposal.get("hypothesis", "")),
        "prediction": str(proposal.get("predicted_observation", "")),
        "protected_behavior": [str(item) for item in proposal.get("protected_behavior", ())],
        "outcome": "passed_public_gate" if decision_passed else "rejected_public_gate",
        "observations": {
            "quality_signal": quality_signal,
            "cost_signal": cost_signal,
            "matched_wins": wins,
            "matched_losses": losses,
            "matched_ties": ties,
            "invalid_candidates": invalid,
            "promotion_path": public_decision.get("promotion_path") if decision_passed else None,
        },
        "failure_clusters": sorted(failure_clusters),
        "source_public_receipt_sha256": content_hash(public_receipt),
        "contains_hidden_evidence": False,
        "contains_absolute_scores": False,
    }
    lesson["lesson_sha256"] = content_hash(lesson)
    return lesson


def load_experiment_lessons(root: Path, domain: str, *, limit: int = 24) -> list[dict[str, Any]]:
    directory = root / "resources" / "public_lessons" / domain
    if not directory.is_dir():
        return []
    lessons: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        value = read_json(path)
        if value.get("public_only") is not True or value.get("contains_hidden_evidence") is not False:
            raise ContractError(f"non-public lesson in public memory: {path}")
        lessons.append(value)
    return lessons[-limit:]

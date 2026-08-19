from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from primus.config import load_domain
from primus.models import LoopStructure
from primus.store import PrimusStore


def pipeline_cost(root: Path, domain: str, *, candidate_calls: int | None = None) -> dict[str, Any]:
    root = root.resolve()
    config = load_domain(root, domain)
    store = PrimusStore(root)
    store.initialize()
    champion = store.champion(domain)
    raw = store.object_bytes(champion["structure_object"], champion["structure_sha256"])
    incumbent_calls = len(LoopStructure.from_dict(json.loads(raw)).calls)
    candidate_calls = int(candidate_calls or config.budget.max_calls)
    if candidate_calls < 1 or candidate_calls > config.budget.max_calls:
        raise ValueError(f"candidate_calls must be 1..{config.budget.max_calls}")
    screen_r = config.evaluation.screening_replicates
    cert_r = config.evaluation.certification_replicates
    portfolio_size = config.exploration.portfolio_size
    probe_r = config.exploration.probe_replicates if portfolio_size > 1 else 0
    probe_calls = probe_r * portfolio_size * candidate_calls
    probe_artifacts = probe_r * portfolio_size
    screen_calls = screen_r * (incumbent_calls + candidate_calls)
    certification_calls = cert_r * (incumbent_calls + candidate_calls)
    screen_artifacts = screen_r * 2
    certification_artifacts = cert_r * 2
    games_per_artifact = 100 if domain == "chess" else 0
    return {
        "domain": domain,
        "incumbent_calls": incumbent_calls,
        "candidate_calls": candidate_calls,
        "architect_calls": portfolio_size,
        "portfolio_probe": {
            "candidates": portfolio_size,
            "replicates": probe_r,
            "executor_calls": probe_calls,
            "evaluated_artifacts": probe_artifacts,
            "chess_games": probe_artifacts * games_per_artifact,
            "hidden_evidence_used": False,
        },
        "screening_reject": {
            "executor_calls": probe_calls + screen_calls,
            "evaluated_artifacts": probe_artifacts + screen_artifacts,
            "chess_games": (probe_artifacts + screen_artifacts) * games_per_artifact,
        },
        "full_certification": {
            "executor_calls": probe_calls + screen_calls + certification_calls,
            "evaluated_artifacts": probe_artifacts + screen_artifacts + certification_artifacts,
            "chess_games": (probe_artifacts + screen_artifacts + certification_artifacts) * games_per_artifact,
        },
        "periodic_control": {
            "interval_rounds": config.evaluation.control_interval_rounds,
            "executor_calls_when_due": candidate_calls * config.evaluation.control_replicates,
            "evaluated_artifacts_when_due": config.evaluation.control_replicates,
            "chess_games_when_due": config.evaluation.control_replicates * games_per_artifact,
            "promotion_gate": False,
        },
    }

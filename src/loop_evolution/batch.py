from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

PAIR_COUNT = 3
PROTOCOL_ID = "matched-three-diverse-anchor-relative-v5"
PROTOCOL_NAME = "OUROBOROS_MATCHED_THREE_DIVERSE_ANCHOR_RELATIVE_V5"
PROMOTION_RULE = (
    "complete three valid pairs; candidate wins > losses; candidate median Elo > incumbent "
    "median Elo; zero invalid arms on either side"
)


@dataclass(frozen=True)
class PairVerdict:
    verdict: str
    incumbent_elo: float | None
    candidate_elo: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "incumbent_elo": self.incumbent_elo,
            "candidate_elo": self.candidate_elo,
        }


def _valid_elo(evaluation: dict[str, Any]) -> float | None:
    value = evaluation.get("elo")
    valid_games = int(evaluation.get("valid_games", 100))
    candidate_failures = int(evaluation.get("candidate_failures", 0))
    if (
        not evaluation.get("valid")
        or valid_games != 100
        or candidate_failures != 0
        or not isinstance(value, (int, float))
    ):
        return None
    return float(value)


def evaluation_is_eligible(evaluation: dict[str, Any]) -> bool:
    return _valid_elo(evaluation) is not None


def pair_verdict(
    incumbent: dict[str, Any], candidate: dict[str, Any]
) -> PairVerdict:
    incumbent_elo = _valid_elo(incumbent)
    candidate_elo = _valid_elo(candidate)
    if candidate_elo is None or incumbent_elo is None:
        verdict = "invalid"
    elif candidate_elo > incumbent_elo:
        verdict = "candidate_win"
    elif candidate_elo < incumbent_elo:
        verdict = "candidate_loss"
    else:
        verdict = "tie"
    return PairVerdict(verdict, incumbent_elo, candidate_elo)


def rejection_is_irreversible(verdicts: list[PairVerdict]) -> bool:
    """Return true only when wins > losses is impossible after remaining pairs."""

    wins = sum(item.verdict == "candidate_win" for item in verdicts)
    losses = sum(item.verdict == "candidate_loss" for item in verdicts)
    remaining = PAIR_COUNT - len(verdicts)
    return wins + remaining <= losses


def _valid_median(evaluations: list[dict[str, Any]]) -> float | None:
    ranked = [_valid_elo(item) for item in evaluations]
    if len(ranked) != PAIR_COUNT or any(value is None for value in ranked):
        return None
    return float(median(float(value) for value in ranked if value is not None))


def _representative_candidate(
    candidates: list[dict[str, Any]],
) -> tuple[int, dict[str, Any]] | None:
    if len(candidates) != PAIR_COUNT or any(_valid_elo(item) is None for item in candidates):
        return None
    ranked = sorted(
        enumerate(candidates, start=1),
        key=lambda item: (float(item[1]["elo"]), item[0]),
    )
    return ranked[1]


def judge_batch(
    *,
    pairs: list[dict[str, Any]],
    anchor_elo: float,
    completed_early: bool = False,
) -> dict[str, Any]:
    verdicts = [
        pair_verdict(pair["incumbent_evaluation"], pair["candidate_evaluation"])
        for pair in pairs
    ]
    wins = sum(item.verdict == "candidate_win" for item in verdicts)
    losses = sum(item.verdict == "candidate_loss" for item in verdicts)
    ties = sum(item.verdict == "tie" for item in verdicts)
    invalid_pairs = sum(item.verdict == "invalid" for item in verdicts)
    incumbents = [pair["incumbent_evaluation"] for pair in pairs]
    candidates = [pair["candidate_evaluation"] for pair in pairs]
    incumbent_median = _valid_median(incumbents)
    candidate_median = _valid_median(candidates)
    representative = _representative_candidate(candidates)
    representative_pair = representative[0] if representative else None
    representative_evaluation = representative[1] if representative else None
    representative_elo = (
        float(representative_evaluation["elo"]) if representative_evaluation else None
    )

    candidate_invalid_count = sum(_valid_elo(item) is None for item in candidates)
    incumbent_invalid_count = sum(_valid_elo(item) is None for item in incumbents)
    checks = {
        "three_valid_pairs_completed": len(pairs) == PAIR_COUNT and invalid_pairs == 0,
        "candidate_wins_strictly_exceed_losses": wins > losses,
        "candidate_median_strictly_exceeds_incumbent": (
            candidate_median is not None
            and incumbent_median is not None
            and candidate_median > incumbent_median
        ),
        "candidate_invalid_count_zero": candidate_invalid_count == 0,
        "incumbent_invalid_count_zero": incumbent_invalid_count == 0,
    }
    promoted = all(checks.values())
    return {
        "schema_version": 2,
        "protocol": PROTOCOL_NAME,
        "planned_pair_count": PAIR_COUNT,
        "completed_pair_count": len(pairs),
        "completed_early": bool(completed_early),
        "anchor_elo": float(anchor_elo),
        "candidate_wins": wins,
        "candidate_losses": losses,
        "ties": ties,
        "invalid_pair_count": invalid_pairs,
        "pair_verdicts": [
            {"pair": index, **verdict.as_dict()}
            for index, verdict in enumerate(verdicts, start=1)
        ],
        "candidate_median_elo": candidate_median,
        "incumbent_median_elo": incumbent_median,
        "median_delta": (
            candidate_median - incumbent_median
            if candidate_median is not None and incumbent_median is not None
            else None
        ),
        "representative_candidate_pair": representative_pair,
        "representative_candidate_elo": representative_elo,
        "candidate_invalid_count": candidate_invalid_count,
        "incumbent_invalid_count": incumbent_invalid_count,
        "promotion_checks": checks,
        "promoted": promoted,
        "inconclusive": invalid_pairs > 0 or len(pairs) != PAIR_COUNT,
        "promotion_rule": PROMOTION_RULE,
    }

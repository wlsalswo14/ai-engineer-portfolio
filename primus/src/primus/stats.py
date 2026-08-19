from __future__ import annotations

import random
import statistics
from typing import Iterable

from primus.models import ArmResult, PairedDecision


def _median(values: Iterable[float]) -> float | None:
    data = list(values)
    return float(statistics.median(data)) if data else None


def _bootstrap_lower(deltas: list[float], confidence: float, samples: int, seed: str) -> float | None:
    if not deltas:
        return None
    if len(deltas) == 1:
        return deltas[0]
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(samples):
        draw = [deltas[rng.randrange(len(deltas))] for _ in deltas]
        means.append(statistics.fmean(draw))
    means.sort()
    index = max(0, min(len(means) - 1, int((1.0 - confidence) * len(means))))
    return float(means[index])


def judge_paired(
    *,
    incumbent: list[ArmResult],
    candidate: list[ArmResult],
    minimum_effect: float,
    confidence: float,
    bootstrap_samples: int,
    seed: str,
    require_confidence: bool,
    rescue_effect: float = 1.0,
) -> PairedDecision:
    if len(incumbent) != len(candidate):
        raise ValueError("paired arms must have equal replicate counts")
    deltas: list[float] = []
    rescue_wins = 0
    both_invalid = 0
    for inc, cand in zip(incumbent, candidate, strict=True):
        incumbent_numeric = inc.valid and inc.score is not None
        candidate_numeric = cand.valid and cand.score is not None
        if incumbent_numeric and candidate_numeric:
            deltas.append(float(cand.score) - float(inc.score))
        elif not incumbent_numeric and candidate_numeric:
            deltas.append(float(rescue_effect))
            rescue_wins += 1
        elif incumbent_numeric and not candidate_numeric:
            deltas.append(-float(rescue_effect))
        else:
            both_invalid += 1
    wins = sum(delta > 0 for delta in deltas)
    losses = sum(delta < 0 for delta in deltas)
    ties = sum(delta == 0 for delta in deltas)
    candidate_values = [float(item.score) for item in candidate if item.valid and item.score is not None]
    incumbent_values = [float(item.score) for item in incumbent if item.valid and item.score is not None]
    candidate_median = _median(candidate_values)
    incumbent_median = _median(incumbent_values)
    median_delta = _median(deltas)
    mean_delta = statistics.fmean(deltas) if deltas else None
    lower = _bootstrap_lower(deltas, confidence, bootstrap_samples, seed)
    invalid_candidate = sum(not item.valid for item in candidate)
    invalid_incumbent = sum(not item.valid for item in incumbent)
    reasons: list[str] = []
    if invalid_candidate:
        reasons.append("candidate_invalid")
    if both_invalid:
        reasons.append("incomplete_valid_pairs")
    if wins <= losses:
        reasons.append("no_pairwise_majority")
    if median_delta is None or median_delta < minimum_effect:
        reasons.append("minimum_effect_not_met")
    if require_confidence and (lower is None or lower <= 0):
        reasons.append("confidence_lower_bound_not_positive")
    candidate_cost = sum(item.usage.effective_tokens for item in candidate)
    incumbent_cost = sum(item.usage.effective_tokens for item in incumbent)
    return PairedDecision(
        passed=not reasons,
        wins=wins,
        losses=losses,
        ties=ties,
        candidate_median=candidate_median,
        incumbent_median=incumbent_median,
        median_delta=median_delta,
        mean_delta=mean_delta,
        lower_confidence_delta=lower,
        invalid_candidate=invalid_candidate,
        invalid_incumbent=invalid_incumbent,
        cost_delta_effective_tokens=candidate_cost - incumbent_cost,
        reasons=tuple(reasons),
        rescue_wins=rescue_wins,
        both_invalid=both_invalid,
    )


def cost_adjusted_score(result: ArmResult, *, token_penalty_per_1k: float, call_penalty: float) -> float | None:
    if not result.valid or result.score is None:
        return None
    return float(result.score) - token_penalty_per_1k * result.usage.effective_tokens / 1000.0 - call_penalty * result.usage.model_calls

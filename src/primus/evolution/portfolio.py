from __future__ import annotations

from typing import Iterable

from primus.models import ArmResult


def rank_public_arms(
    results: dict[str, list[ArmResult]],
    candidate_arms: Iterable[str],
) -> list[str]:
    """Rank public candidates by validity, quality, then generation cost."""
    names = list(candidate_arms)

    def rank(name: str) -> tuple[float, float, float, str]:
        values = results.get(name, [])
        if not values:
            return (0.0, float("-inf"), float("-inf"), name)
        valid = [item for item in values if item.valid and item.score is not None]
        validity = len(valid) / len(values)
        quality = sum(float(item.score) for item in valid) / len(valid) if valid else float("-inf")
        cost = sum(item.usage.effective_tokens for item in values)
        return (validity, quality, -float(cost), name)

    return sorted(names, key=rank, reverse=True)

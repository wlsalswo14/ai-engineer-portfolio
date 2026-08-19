from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdaptiveSearchPolicy:
    cycle: tuple[str, ...]
    novelty_interval_rounds: int = 5
    adaptive: bool = True

    def choose(self, *, round_index: int, lessons: list[dict[str, Any]]) -> str:
        scheduled = self.cycle[(round_index - 1) % len(self.cycle)]
        if not self.adaptive or not lessons:
            return scheduled

        if round_index % self.novelty_interval_rounds == 0:
            novelty = "research_transfer" if "research_transfer" in self.cycle else "de_novo"
            return novelty if novelty in self.cycle else scheduled

        latest = lessons[-1]
        clusters = " ".join(str(item) for item in latest.get("failure_clusters", ())).casefold()
        observations = latest.get("observations", {})
        quality = str(observations.get("quality_signal", ""))
        cost = str(observations.get("cost_signal", ""))
        preference: list[str]
        if any(marker in clusters for marker in ("timeout", "cost", "budget")) or cost == "higher":
            preference = ["delete", "replace", "recombine"]
        elif any(marker in clusters for marker in ("invalid", "contract", "forbidden", "protected", "parse")):
            preference = ["replace", "recombine", "add"]
        elif quality == "mostly_regressed":
            preference = ["recombine", "replace", "de_novo"]
        elif latest.get("outcome") == "passed_public_gate":
            preference = ["add", "recombine", "open"]
        else:
            preference = [scheduled, "replace", "recombine"]

        # Avoid immediately repeating an operator that just failed when another
        # compatible choice exists.
        last_operation = str(latest.get("operation", ""))
        for operation in preference:
            if operation in self.cycle and operation != last_operation:
                return operation
        return scheduled

    def portfolio_modes(self, *, primary: str, size: int) -> tuple[str, ...]:
        if size <= 1:
            return (primary,)
        safe_cycle = [item for item in self.cycle if item != "research_transfer"]
        modes = [primary]
        for operation in safe_cycle:
            if operation not in modes:
                modes.append(operation)
            if len(modes) == size:
                break
        while len(modes) < size:
            modes.append("open")
        return tuple(modes)

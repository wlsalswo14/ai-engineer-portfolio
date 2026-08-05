from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loop_evolution.common import content_hash

BUILTIN_INPUTS = frozenset(
    {
        "task",
        "champion_engine",
        "champion_metrics",
        "state_capsule",
        "candidate_hypothesis",
        "loop_structure",
    }
)


class PlanValidationError(ValueError):
    pass


EMERGENT_CAPABILITY_FIELDS = (
    "capability_family",
    "champion_limitation",
    "emergent_capability",
    "trigger",
    "state_transition",
    "observable_effect",
    "novelty_probe",
    "not_local_refinement",
)


@dataclass(frozen=True)
class LoopPlan:
    payload: dict[str, Any]
    structure_id: str

    @classmethod
    def from_payload(cls, raw: dict[str, Any], *, expected_mode: str) -> LoopPlan:  # noqa: C901
        payload = dict(raw)
        if payload.get("schema_version") != 1:
            raise PlanValidationError("candidate plan schema_version must be 1")

        hypothesis = payload.get("hypothesis")
        structure = payload.get("structure")
        compliance = payload.get("compliance")
        if not isinstance(hypothesis, dict) or not isinstance(structure, dict):
            raise PlanValidationError("candidate plan requires hypothesis and structure objects")
        if not isinstance(compliance, dict):
            raise PlanValidationError("candidate plan requires a compliance object")

        required_hypothesis = (
            "observed_bottleneck",
            "evidence_refs",
            "causal_change",
            "expected_effect",
            "falsifier",
            "behavioral_novelty",
            "strengths",
            "risks",
        )
        for key in required_hypothesis:
            if key not in hypothesis:
                raise PlanValidationError(f"hypothesis is missing {key}")
        evidence = hypothesis["evidence_refs"]
        if not isinstance(evidence, list) or not evidence:
            raise PlanValidationError("hypothesis evidence_refs must be a non-empty list")

        change = hypothesis["causal_change"]
        if not isinstance(change, dict) or int(change.get("change_count", 0)) != 1:
            raise PlanValidationError("candidate must declare exactly one causal structural change")
        for key in ("factor", "before", "after", "why_causal"):
            if not str(change.get(key, "")).strip():
                raise PlanValidationError(f"causal_change is missing {key}")

        forbidden_flags = (
            "changes_model_or_effort",
            "changes_benchmark_or_promotion",
            "tunes_engine_hyperparameters_as_structure",
            "hardcodes_benchmark",
        )
        for key in forbidden_flags:
            if compliance.get(key) is not False:
                raise PlanValidationError(f"compliance.{key} must be false")

        mode = str(payload.get("proposal_mode", ""))
        if mode != expected_mode:
            raise PlanValidationError(f"proposal_mode must be {expected_mode}")
        if expected_mode == "counter_hypothesis":
            if not str(hypothesis.get("dominant_assumption", "")).strip():
                raise PlanValidationError("counter-hypothesis mode requires dominant_assumption")
            if not str(hypothesis.get("inversion", "")).strip():
                raise PlanValidationError("counter-hypothesis mode requires inversion")
        if expected_mode == "emergent_exploration":
            capability = hypothesis.get("emergent_capability")
            if not isinstance(capability, dict):
                raise PlanValidationError(
                    "emergent-exploration mode requires hypothesis.emergent_capability"
                )
            for key in EMERGENT_CAPABILITY_FIELDS:
                value = capability.get(key)
                if key == "state_transition":
                    if not isinstance(value, dict):
                        raise PlanValidationError(
                            "emergent_capability.state_transition must contain before and after"
                        )
                    if not str(value.get("before", "")).strip() or not str(
                        value.get("after", "")
                    ).strip():
                        raise PlanValidationError(
                            "emergent_capability.state_transition requires before and after"
                        )
                elif not str(value or "").strip():
                    raise PlanValidationError(f"emergent_capability is missing {key}")

        organization = str(structure.get("organization", ""))
        if organization not in {"solo", "collaboration"}:
            raise PlanValidationError("structure.organization must be solo or collaboration")
        stages = structure.get("stages")
        if not isinstance(stages, list) or not stages:
            raise PlanValidationError("structure.stages must be a non-empty list")

        available = set(BUILTIN_INPUTS)
        call_ids: set[str] = set()
        call_count = 0
        output_types: dict[str, str] = {}
        for stage_index, stage in enumerate(stages):
            if not isinstance(stage, dict) or stage.get("mode") not in {"parallel", "sequential"}:
                raise PlanValidationError(f"stage {stage_index} has an invalid mode")
            calls = stage.get("calls")
            if not isinstance(calls, list) or not calls:
                raise PlanValidationError(f"stage {stage_index} has no calls")
            stage_ids: set[str] = set()
            for call in calls:
                if not isinstance(call, dict):
                    raise PlanValidationError("every call must be an object")
                call_id = str(call.get("id", "")).strip()
                if not call_id or call_id in call_ids or call_id in BUILTIN_INPUTS:
                    raise PlanValidationError(f"invalid or duplicate call id: {call_id!r}")
                if not str(call.get("role", "")).strip() or not str(call.get("objective", "")).strip():
                    raise PlanValidationError(f"call {call_id} needs role and objective")
                output_type = str(call.get("output_type", ""))
                if output_type not in {"analysis", "engine"}:
                    raise PlanValidationError(f"call {call_id} has invalid output_type")
                inputs = call.get("inputs")
                if not isinstance(inputs, list):
                    raise PlanValidationError(
                        f"call {call_id} may reference only built-ins or outputs from earlier stages"
                    )
                normalized_inputs = [
                    str(item)[:-7]
                    if str(item).endswith(".output") and str(item)[:-7] in available
                    else str(item)
                    for item in inputs
                ]
                if any(item not in available for item in normalized_inputs):
                    raise PlanValidationError(
                        f"call {call_id} may reference only built-ins or outputs from earlier stages"
                    )
                call["inputs"] = normalized_inputs
                stage_ids.add(call_id)
                call_ids.add(call_id)
                output_types[call_id] = output_type
                call_count += 1
            available.update(stage_ids)

        final_call_id = str(structure.get("final_call_id", ""))
        if final_call_id not in call_ids or output_types.get(final_call_id) != "engine":
            raise PlanValidationError("final_call_id must identify an engine-producing call")
        if organization == "solo" and call_count != 1:
            raise PlanValidationError("a solo structure must contain exactly one self-contained engine call")
        if organization == "collaboration" and call_count < 2:
            raise PlanValidationError("a collaboration structure must contain at least two calls")

        normalized = {
            "schema_version": 1,
            "proposal_mode": mode,
            "hypothesis": hypothesis,
            "structure": structure,
            "compliance": {key: False for key in forbidden_flags},
        }
        structure_id = f"loop_{content_hash(normalized)[:16]}"
        normalized["structure_id"] = structure_id
        return cls(normalized, structure_id)

    def validate_search_context(self, capsule: dict[str, Any]) -> None:
        """Validate round-specific search constraints that are not intrinsic to the plan."""

        if self.payload["proposal_mode"] != "emergent_exploration":
            return
        capability = self.payload["hypothesis"]["emergent_capability"]
        family = str(capability["capability_family"]).strip().casefold()
        prior = {
            str(item).strip().casefold()
            for item in capsule.get("search_control", {}).get(
                "emergent_capability_families_already_tested", []
            )
            if str(item).strip()
        }
        if family in prior:
            raise PlanValidationError(
                "the second emergent attempt must use a different capability_family"
            )

    @property
    def hypothesis(self) -> dict[str, Any]:
        return dict(self.payload["hypothesis"])

    @property
    def structure(self) -> dict[str, Any]:
        return dict(self.payload["structure"])

    @property
    def proposal_mode(self) -> str:
        return str(self.payload["proposal_mode"])


def direct_control_plan() -> LoopPlan:
    """Frozen single-call Luna control used only for external calibration."""

    payload = {
        "schema_version": 1,
        "proposal_mode": "general",
        "hypothesis": {
            "observed_bottleneck": "External calibration requires the unaugmented single-model baseline.",
            "evidence_refs": ["official same-model Direct Codex control contract"],
            "causal_change": {
                "change_count": 1,
                "factor": "absence of an added collaboration harness",
                "before": "champion loop structure",
                "after": "one direct self-contained Luna high coding call",
                "why_causal": "It measures the total value added by the installed harness.",
            },
            "expected_effect": "Provide an external calibration score, not an evolutionary candidate.",
            "falsifier": "The direct artifact is invalid or the frozen comparison cannot be completed.",
            "behavioral_novelty": (
                "No added harness; the model directly analyzes, edits, checks, and returns the engine."
            ),
            "strengths": ["simple same-model baseline"],
            "risks": ["does not isolate compute efficiency when harness call counts differ"],
        },
        "structure": {
            "name": "same_model_direct_luna_control",
            "organization": "solo",
            "information_flow": (
                "The task, anchor engine, and metrics enter one self-contained Luna high coding call."
            ),
            "stages": [
                {
                    "id": "direct",
                    "mode": "sequential",
                    "calls": [
                        {
                            "id": "direct_engine",
                            "role": "Direct Luna high chess-engine developer",
                            "objective": (
                                "Directly improve the anchor into one complete legal UCI engine. Use ordinary "
                                "coding tools and general development checks without any added collaboration "
                                "protocol or benchmark-specific knowledge."
                            ),
                            "inputs": ["task", "champion_engine", "champion_metrics"],
                            "output_type": "engine",
                            "allow_search": True,
                        }
                    ],
                }
            ],
            "final_call_id": "direct_engine",
        },
        "compliance": {
            "changes_model_or_effort": False,
            "changes_benchmark_or_promotion": False,
            "tunes_engine_hyperparameters_as_structure": False,
            "hardcodes_benchmark": False,
        },
    }
    return LoopPlan.from_payload(payload, expected_mode="general")

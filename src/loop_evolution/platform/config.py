from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class PolicyConfigurationError(ValueError):
    pass


PLANNER_PER_CASE_ROUTING = "planner_per_case"
PLANNER_SELECTED_FIXED_ROUTING = "fixed_target_slot"
POLICY_FIXED_ROUTING = "fixed_policy_slot"
FIXED_SLOT_ROUTING_MODES = frozenset(
    {PLANNER_SELECTED_FIXED_ROUTING, POLICY_FIXED_ROUTING}
)


def is_fixed_slot_routing(mode: str) -> bool:
    return mode in FIXED_SLOT_ROUTING_MODES


def _validate_harness_slots(slots: tuple[str, ...], *, label: str) -> None:
    if (
        not slots
        or len(set(slots)) != len(slots)
        or not set(slots).issubset({"slot_1", "slot_2", "slot_3"})
    ):
        raise PolicyConfigurationError(
            f"{label} harness slots must be a unique non-empty subset of slot_1..slot_3"
        )


def _reject_paid_environment() -> None:
    paid_credentials = tuple(name for name in ("OPENAI_API_KEY", "CODEX_API_KEY") if os.environ.get(name))
    if paid_credentials:
        raise PolicyConfigurationError(
            "paid API credentials are present and live execution is fail-closed: " + ", ".join(paid_credentials)
        )


def _validate_codex_home_pool(
    homes: tuple[str, ...],
    *,
    require_live_auth: bool,
) -> None:
    if len(set(homes)) != len(homes):
        raise PolicyConfigurationError("Codex subscription homes must be unique")
    for raw_home in homes:
        home = Path(raw_home)
        if not raw_home or not home.is_absolute():
            raise PolicyConfigurationError("Codex subscription homes must be absolute paths")
        if not require_live_auth:
            continue
        auth_path = home / "auth.json"
        if not auth_path.is_file():
            raise PolicyConfigurationError(f"Codex subscription home has no auth.json: {home}")
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyConfigurationError(f"Codex subscription auth is unreadable: {home}") from exc
        if (
            not isinstance(auth, dict)
            or auth.get("auth_mode") != "chatgpt"
            or bool(auth.get("OPENAI_API_KEY"))
            or not isinstance(auth.get("tokens"), dict)
        ):
            raise PolicyConfigurationError(
                f"Codex home is not a ChatGPT-subscription-only login: {home}"
            )


@dataclass(frozen=True)
class RuntimePolicy:
    model: str = "gpt-5.6-luna"
    reasoning_effort: str = "medium"
    auth_mode: str = "codex_subscription"
    allow_paid_api: bool = False
    allow_model_fallback: bool = False
    sandbox: str = "read-only"
    max_model_calls: int = 8
    max_tokens: int = 64_000
    max_wall_seconds: int = 900
    treat_wall_time_limit_as_incorrect: bool = False
    allow_direct_supervisor_on_quota: bool = False
    evaluation_epoch: str = "v3lite-v1"
    evaluator_version: str = "fixed-v1"
    codex_executable: str = "codex"
    codex_home_pool: tuple[str, ...] = ()
    allowed_harness_slots: tuple[str, ...] = ("slot_1", "slot_2", "slot_3")
    enable_harness_planner: bool = True

    @classmethod
    def load(cls, path: Path) -> RuntimePolicy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("schema_version", None)
        if "allowed_harness_slots" in payload:
            payload["allowed_harness_slots"] = tuple(payload["allowed_harness_slots"])
        if "codex_home_pool" in payload:
            payload["codex_home_pool"] = tuple(payload["codex_home_pool"])
        policy = cls(**payload)
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.model != "gpt-5.6-luna" or self.auth_mode != "codex_subscription":
            raise PolicyConfigurationError("only gpt-5.6-luna with Codex subscription authentication is allowed")
        if self.reasoning_effort not in {"medium", "high"}:
            raise PolicyConfigurationError("reasoning effort must be medium or explicitly selected high")
        if self.allow_paid_api:
            raise PolicyConfigurationError("paid API execution is forbidden")
        if self.allow_model_fallback:
            raise PolicyConfigurationError("model fallback is forbidden")
        if self.sandbox != "read-only":
            raise PolicyConfigurationError("V3-lite model execution must remain read-only")
        if min(self.max_model_calls, self.max_tokens, self.max_wall_seconds) <= 0:
            raise PolicyConfigurationError("all budget limits must be positive")
        if not isinstance(self.treat_wall_time_limit_as_incorrect, bool):
            raise PolicyConfigurationError("wall-time outcome policy must be a boolean")
        if not isinstance(self.allow_direct_supervisor_on_quota, bool):
            raise PolicyConfigurationError("direct quota fallback policy must be a boolean")
        if not isinstance(self.enable_harness_planner, bool):
            raise PolicyConfigurationError("harness planner policy must be a boolean")
        if not self.evaluator_version:
            raise PolicyConfigurationError("evaluator version must be pinned")
        _validate_codex_home_pool(tuple(self.codex_home_pool), require_live_auth=False)
        allowed_slots = tuple(self.allowed_harness_slots)
        _validate_harness_slots(allowed_slots, label="allowed")
        if not self.enable_harness_planner and len(allowed_slots) != 1:
            raise PolicyConfigurationError(
                "disabling the harness planner requires exactly one allowed harness slot"
            )

    def validate_live_environment(self) -> None:
        self.validate()
        _reject_paid_environment()
        _validate_codex_home_pool(tuple(self.codex_home_pool), require_live_auth=True)


def runtime_policy_identity(policy: RuntimePolicy) -> dict[str, Any]:
    """Stable evaluation identity; account routing is recorded in traces, not capability."""

    payload = asdict(policy)
    payload.pop("codex_home_pool", None)
    return payload


@dataclass(frozen=True)
class ProposalPolicy:
    """Codex-subscription-only policy for the structural package architect."""

    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "xhigh"
    auth_mode: str = "codex_subscription"
    allow_paid_api: bool = False
    allow_model_fallback: bool = False
    sandbox: str = "read-only"
    max_model_calls: int = 1
    max_tokens: int = 120_000
    max_wall_seconds: int = 900
    codex_executable: str = "codex"
    codex_home_pool: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> ProposalPolicy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("schema_version", None)
        if "codex_home_pool" in payload:
            payload["codex_home_pool"] = tuple(payload["codex_home_pool"])
        policy = cls(**payload)
        policy.validate()
        return policy

    def validate(self) -> None:
        if (
            self.model != "gpt-5.6-sol"
            or self.reasoning_effort not in {"xhigh", "max"}
            or self.auth_mode != "codex_subscription"
        ):
            raise PolicyConfigurationError(
                "structural proposals require Sol xhigh/max with Codex subscription"
            )
        if self.allow_paid_api or self.allow_model_fallback:
            raise PolicyConfigurationError("paid API execution and model fallback are forbidden")
        if self.sandbox != "read-only":
            raise PolicyConfigurationError("proposal execution must remain read-only")
        if min(self.max_model_calls, self.max_tokens, self.max_wall_seconds) <= 0:
            raise PolicyConfigurationError("all proposal budget limits must be positive")
        _validate_codex_home_pool(tuple(self.codex_home_pool), require_live_auth=False)

    def validate_live_environment(self) -> None:
        self.validate()
        _reject_paid_environment()
        _validate_codex_home_pool(tuple(self.codex_home_pool), require_live_auth=True)


@dataclass(frozen=True)
class StructuralEvolutionPolicy:
    """Replaceable control policy for package size and staged evaluation."""

    minimum_package_changes: int = 2
    maximum_package_changes: int = 5
    screening_enabled: bool = True
    evaluation_routing_mode: str = "planner_per_case"
    screening_case_count: int = 3
    allowed_harness_slots: tuple[str, ...] = ("slot_1", "slot_2", "slot_3")
    screening_requires_candidate_win: bool = True
    max_ablation_rounds: int = 4
    require_external_benchmark_provenance: bool = False
    require_champion_accuracy_calibration: bool = False
    use_calibration_pools_as_fixed_suites: bool = False
    champion_target_accuracy: float = 0.70
    champion_accuracy_tolerance: float = 0.02
    calibrated_suite_case_count: int = 7
    calibration_selection_mode: str = "quota"
    recalibrate_after_promotion: bool = True
    evaluation_policy_version: str = "structural-v1"
    enable_planner_selection_supervision: bool = False
    planner_supervision_batch_size: int = 8
    max_alternative_confirmations_per_proposal: int = 1
    allow_direct_supervisor_on_quota: bool = False
    single_harness_change: bool = False
    first_principles_after_non_promotions: int = 0

    @classmethod
    def load(cls, path: Path) -> StructuralEvolutionPolicy:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("schema_version", None)
        if "allowed_harness_slots" in payload:
            payload["allowed_harness_slots"] = tuple(payload["allowed_harness_slots"])
        policy = cls(**payload)
        policy.validate()
        return policy

    def validate(self) -> None:
        if not self.evaluation_policy_version.strip():
            raise PolicyConfigurationError("structural evaluation policy version must be pinned")
        self._validate_planner_supervision()
        self._validate_package_policy()
        self._validate_routing_policy()
        self._validate_suite_policy()
        self._validate_calibration()

    def _validate_planner_supervision(self) -> None:
        if self.planner_supervision_batch_size <= 0:
            raise PolicyConfigurationError("planner supervision batch size must be positive")
        if self.max_alternative_confirmations_per_proposal not in {0, 1}:
            raise PolicyConfigurationError(
                "planner supervision permits at most one alternative confirmation per proposal"
            )
        if not isinstance(self.allow_direct_supervisor_on_quota, bool):
            raise PolicyConfigurationError("direct quota fallback policy must be a boolean")

    def _validate_package_policy(self) -> None:
        if not 1 <= self.minimum_package_changes <= self.maximum_package_changes:
            raise PolicyConfigurationError("structural package change limits are invalid")
        if self.maximum_package_changes > 5:
            raise PolicyConfigurationError("structural packages may contain at most five changes")
        if not isinstance(self.screening_enabled, bool):
            raise PolicyConfigurationError("screening enabled policy must be a boolean")
        if not isinstance(self.single_harness_change, bool):
            raise PolicyConfigurationError("single harness change policy must be a boolean")
        if self.single_harness_change and (
            self.minimum_package_changes != 1 or self.maximum_package_changes != 1
        ):
            raise PolicyConfigurationError(
                "single harness change mode requires minimum_package_changes=maximum_package_changes=1"
            )
        if (
            not isinstance(self.first_principles_after_non_promotions, int)
            or self.first_principles_after_non_promotions < 0
        ):
            raise PolicyConfigurationError(
                "first-principles non-promotion threshold must be a non-negative integer"
            )

    def _validate_routing_policy(self) -> None:
        if self.evaluation_routing_mode not in {
            PLANNER_PER_CASE_ROUTING,
            PLANNER_SELECTED_FIXED_ROUTING,
            POLICY_FIXED_ROUTING,
        }:
            raise PolicyConfigurationError(
                "evaluation routing mode must be planner_per_case, fixed_target_slot, or fixed_policy_slot"
            )
        _validate_harness_slots(tuple(self.allowed_harness_slots), label="structural evolution")
        if self.evaluation_routing_mode != POLICY_FIXED_ROUTING:
            return
        if len(self.allowed_harness_slots) != 1:
            raise PolicyConfigurationError(
                "fixed_policy_slot routing requires exactly one structural evolution slot"
            )
        if self.enable_planner_selection_supervision:
            raise PolicyConfigurationError(
                "planner selection supervision cannot run when routing is policy-fixed"
            )

    def _validate_suite_policy(self) -> None:
        if self.screening_case_count <= 0:
            raise PolicyConfigurationError("screening case count must be positive")
        if not isinstance(self.use_calibration_pools_as_fixed_suites, bool):
            raise PolicyConfigurationError("fixed-suite pool policy must be a boolean")
        if self.require_champion_accuracy_calibration and self.use_calibration_pools_as_fixed_suites:
            raise PolicyConfigurationError(
                "champion calibration and fixed-suite pool loading are mutually exclusive"
            )
        if self.require_champion_accuracy_calibration and not self.screening_enabled:
            raise PolicyConfigurationError(
                "champion-calibrated evolution requires the screening stage"
            )
        if self.max_ablation_rounds <= 0:
            raise PolicyConfigurationError("ablation round limit must be positive")

    @property
    def policy_fixed_slot(self) -> str | None:
        if self.evaluation_routing_mode != POLICY_FIXED_ROUTING:
            return None
        return self.allowed_harness_slots[0]

    def _validate_calibration(self) -> None:
        if self.calibration_selection_mode not in {"quota", "fixed_window"}:
            raise PolicyConfigurationError(
                "calibration selection mode must be 'quota' or 'fixed_window'"
            )
        if not 0 < self.champion_target_accuracy < 1:
            raise PolicyConfigurationError("champion target accuracy must be between zero and one")
        if not 0 <= self.champion_accuracy_tolerance < 1:
            raise PolicyConfigurationError("champion accuracy tolerance must be in [0, 1)")
        if self.calibrated_suite_case_count < 2:
            raise PolicyConfigurationError("calibrated suites require at least two cases")
        calibrated_passes = round(self.champion_target_accuracy * self.calibrated_suite_case_count)
        calibrated_accuracy = calibrated_passes / self.calibrated_suite_case_count
        if (
            self.require_champion_accuracy_calibration
            and self.calibration_selection_mode == "quota"
            and abs(calibrated_accuracy - self.champion_target_accuracy) > self.champion_accuracy_tolerance
        ):
            raise PolicyConfigurationError(
                "calibrated suite size cannot represent the target accuracy within tolerance"
            )
        if self.require_champion_accuracy_calibration and self.screening_case_count != self.calibrated_suite_case_count:
            raise PolicyConfigurationError("screening case count must equal calibrated suite case count")
        if self.require_champion_accuracy_calibration and not self.recalibrate_after_promotion:
            raise PolicyConfigurationError("champion-calibrated evolution must recalibrate after every promotion")


def validate_harness_policy_compatibility(
    runtime: RuntimePolicy,
    structural: StructuralEvolutionPolicy,
) -> None:
    """Fail closed when execution and evolution disagree about active slots or routing ownership."""

    runtime_slots = tuple(runtime.allowed_harness_slots)
    structural_slots = tuple(structural.allowed_harness_slots)
    if runtime_slots != structural_slots:
        raise PolicyConfigurationError(
            "runtime and structural policies must enable the same ordered harness slots"
        )
    if runtime.enable_harness_planner:
        if structural.evaluation_routing_mode == POLICY_FIXED_ROUTING:
            raise PolicyConfigurationError(
                "fixed_policy_slot routing requires the runtime harness planner to be disabled"
            )
        return
    if structural.evaluation_routing_mode != POLICY_FIXED_ROUTING:
        raise PolicyConfigurationError(
            "a disabled runtime harness planner requires fixed_policy_slot evolution routing"
        )

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from loop_evolution.platform.backends.codex import CodexBackend
from loop_evolution.platform.config import (
    ProposalPolicy,
    RuntimePolicy,
    proposal_policy_identity,
    runtime_policy_identity,
)
from loop_evolution.platform.runtime.answers import extract_final_answer
from loop_evolution.common import atomic_json, canonical_json, content_hash, parse_json_object, read_json
from loop_evolution.plan import LoopPlan, PlanValidationError


@dataclass(frozen=True)
class ModelCall:
    text: str
    usage: dict[str, Any]
    trace_refs: tuple[str, ...]


class CodexModelClient:
    """Create one backend per call and rotate the configured subscription-home order."""

    def __init__(self, policy: ProposalPolicy | RuntimePolicy) -> None:
        self.policy = policy
        self._lock = threading.Lock()
        self._call_index = 0

    def complete(
        self,
        *,
        role: str,
        prompt: str,
        working_directory: Path,
        allow_workspace_read: bool,
        allow_search: bool = False,
    ) -> ModelCall:
        with self._lock:
            call_index = self._call_index
            self._call_index += 1
        homes = tuple(self.policy.codex_home_pool)
        if homes:
            offset = call_index % len(homes)
            policy = replace(self.policy, codex_home_pool=homes[offset:] + homes[:offset])
        else:
            policy = self.policy
        backend = CodexBackend(policy)
        response = backend.complete_with_tools(
            role=role,
            prompt=prompt,
            working_directory=str(working_directory),
            allowed_tools=(
                (("search", "workspace_read", "command") if allow_search else ("workspace_read", "command"))
                if allow_workspace_read
                else (("search",) if allow_search else ())
            ),
            timeout_seconds=policy.max_wall_seconds,
        )
        return ModelCall(response.text, asdict(response.usage), tuple(response.trace_refs))


def architect_prompt(capsule: dict[str, Any], *, validation_feedback: str = "") -> str:
    mode = str(capsule["search_control"]["proposal_mode"])
    development = capsule.get("development_candidate")
    has_development = isinstance(development, dict) and bool(development)
    if has_development:
        design_parent_instruction = (
            "The official champion remains the promotion opponent, but it is not this round's design parent. "
            "Refine the active development candidate described in STATE_CAPSULE.development_candidate. Read only "
            "its exact execution_plan_path when the summary is insufficient. Preserve that candidate's structural "
            "family unless EMERGENT-EXPLORATION MODE explicitly asks for a new capability within the family."
        )
        development_schema = '''
    "development_lineage": {
      "parent_structure_id": "exact structure_id from STATE_CAPSULE.development_candidate",
      "preserved_family": "exact structural_family from STATE_CAPSULE.development_candidate",
      "relationship": "general_refinement|emergent_extension"
    },'''
    else:
        design_parent_instruction = (
            "There is no active development candidate. In local or emergent mode, the official champion is the "
            "design parent. In counter-hypothesis mode, the official champion is evidence and the promotion "
            "opponent, but must not be used as a template or parent."
        )
        development_schema = ""
    if mode == "counter_hypothesis":
        mode_instruction = (
            "COUNTER-HYPOTHESIS MODE searches for a genuinely different structural family and persists until a "
            "candidate either promotes or retains at least the configured development threshold of champion "
            "performance. Extract the champion family's causal principle, reject one or two core assumptions, and "
            "declare the champion mechanisms that the candidate is forbidden to use. Design from a replacement "
            "causal principle rather than editing or reversing the champion stage-by-stage. A role rename, reordered "
            "version of the same draft-review-integrate flow, extra gate, or collaboration/solo switch alone is not "
            "a family break. One replacement principle may have consequences across multiple dimensions while still "
            "counting as the single causal factor. Explain at least two changed behavioral dimensions and provide a "
            "probe that can distinguish the new family from the champion on the same evidence. Use an "
            "alternative_family not listed in counter_families_already_tested. Fill dominant_assumption, inversion, "
            "and family_break completely."
        )
        mode_schema = '''
    "family_break": {
      "champion_family": "compact causal description of the incumbent family",
      "alternative_family": "stable compact name for the independent replacement family",
      "rejected_core_assumptions": ["one or two assumptions rejected by this candidate"],
      "forbidden_champion_mechanisms": ["mechanism that must not reappear under another name"],
      "alternative_causal_principle": "one replacement principle from which the structure is derived",
      "changed_dimensions": ["at least two of information_flow|error_detection|candidate_selection|final_decision|failure_recovery"],
      "difference_from_champion": {"information_flow": "concrete behavioral difference for every listed dimension"},
      "non_derivative_probe": "probe distinguishing the new family from the champion on the same evidence"
    },'''
    elif mode == "emergent_exploration":
        parent_name = "development candidate" if has_development else "champion"
        mode_instruction = (
            f"EMERGENT-EXPLORATION MODE. Preserve the supported {parent_name} family but enable one observable action "
            f"that the {parent_name}'s current control flow cannot perform. A larger packet, an extra certificate field, a "
            "moved audit, a finer rollback scope, a renamed ledger, or an added reviewer/gate is not emergent unless "
            "it creates a genuinely new trigger-dependent state transition and decision path. Derive the capability "
            "from the evidence rather than choosing from a fixed menu. Do not merely repair the previous emergent "
            "attempt. If search_control lists a previously tested emergent capability family, choose a different "
            "family. Fill hypothesis.emergent_capability completely and make its novelty_probe executable or "
            "otherwise concretely observable."
        )
        mode_schema = '''
    "emergent_capability": {
      "capability_family": "stable compact name for the new kind of behavior",
      "champion_limitation": "behavior the current champion structurally cannot perform",
      "emergent_capability": "new observable action enabled by the candidate",
      "trigger": "runtime evidence or condition that activates the new action",
      "state_transition": {"before": "pre-trigger work state", "after": "new post-trigger work state"},
      "observable_effect": "how the candidate trajectory differs from the champion on the same evidence",
      "novelty_probe": "concrete probe showing that the new path occurs",
      "not_local_refinement": "why this is not another certificate, audit, rollback, packet, or role-detail refinement"
    },'''
    else:
        parent_name = "development candidate" if has_development else "champion"
        mode_instruction = (
            f"LOCAL-REFINEMENT MODE. Make one evidence-led causal refinement while preserving the {parent_name}'s macro "
            "capability family. This round counts toward the two-round local budget whether or not it promotes. Do "
            "not fill dominant_assumption or inversion merely for novelty."
        )
        mode_schema = ""
    retry_instruction = (
        "\nThe preceding proposal was rejected before evaluation. Correct the stated contract violation while "
        f"still proposing one coherent candidate. VALIDATION_FEEDBACK={validation_feedback}\n"
        if validation_feedback
        else ""
    )
    return f"""You are an independent Sol max structural-architect subagent evolving a loop structure, not a chess engine.

The official champion is one indivisible package: loop structure plus the engine that structure produced. Propose one
new loop structure that will start from the supplied anchor engine and attempt to produce a stronger engine.
{design_parent_instruction} The candidate and official champion structures will each run from the exact same anchor in
three matched pairs. Their final
engines are evaluated by the frozen ChessBench; promotion requires paired superiority, candidate-median superiority,
and zero invalid arms. A counter-hypothesis batch that does not promote may enter a bounded development cycle only when
its median score-rate ratio is at least 90%, proven either by three valid pairs or by decisive two-pair worst-case bounds
after formal promotion is already impossible. Do not apply
percentages to negative Elo. The precommitted median-ranked candidate engine represents a winning or development batch. Solo and
collaboration are two
allowed organizations in the same lineage. Direct is only an external same-model calibration control, never a
candidate, champion, or promotion opponent.

Use the bounded STATE_CAPSULE below as your default evidence. It contains previous candidates' conditional strengths,
weaknesses, lessons, the final goal, and the current champion summary. Do not ingest the whole archive. If one specific
claim truly requires older evidence, inspect only the exact round or structure file needed through read-only workspace
tools. Never use web search or external files.

Change exactly one causal structural factor. Supporting operational details may change only as necessary to
instantiate that one factor. A switch between solo and collaboration counts as one factor. Explain the observed
evidence,
expected behavioral effect, risks, a decisive matched-batch falsifier, and the new behavior that this factor can cause.
Do not confuse role-count, arrow-layout, or sampling multiplicity with behavioral novelty. A candidate loop must not
contain replicated candidates, agents, samples, or near-identical calls followed by best-of-N selection. This applies
even when that multiplicity is inherited from the champion: remove or replace it rather than extend it. Additional calls
are allowed only when each performs a distinct information transformation that cannot be replaced by another sample of
the same role. Prefer mechanisms involving executable evidence, bounded repair, rollback, or information preservation
when supported, but do not force any one family. {mode_instruction}{retry_instruction}

The structural hypothesis must not change the model/reasoning effort, benchmark, evaluator, Elo calculation, promotion
rule, or task. Do not make engine hyperparameter tuning or benchmark hard-coding the structural hypothesis. The proposed
loop may use any finite number of calls; construction cost is not matched against the incumbent. A solo loop has exactly
one self-contained engine-producing call. A collaboration loop has at least two calls. Stages run in order; calls within
a parallel stage cannot consume one another. Every input must be a built-in or an output from an earlier stage. The
final
call must produce a complete engine.

Built-in inputs are exactly: task, champion_engine, champion_metrics, state_capsule, candidate_hypothesis,
loop_structure.
Call output_type is analysis or engine. Return exactly one JSON object and no Markdown:
{{
  "schema_version": 1,
  "proposal_mode": "{mode}",
  "hypothesis": {{
    "observed_bottleneck": "string",
    "evidence_refs": ["capsule or targeted archive reference"],
    "causal_change": {{
      "change_count": 1,
      "factor": "one structural factor",
      "before": "current value/assumption",
      "after": "candidate value/assumption",
      "why_causal": "string"
    }},
    "expected_effect": "behavioral prediction",
    "falsifier": "decisive three-pair batch condition",
    "behavioral_novelty": "new observable behavior enabled by the one causal change",
{development_schema}
{mode_schema}
    "strengths": ["predicted strength"],
    "risks": ["predicted weakness"],
    "dominant_assumption": "required only in counter_hypothesis mode",
    "inversion": "required only in counter_hypothesis mode"
  }},
  "structure": {{
    "name": "string",
    "organization": "solo|collaboration",
    "information_flow": "compact explanation",
    "stages": [{{
      "id": "stage_id",
      "mode": "parallel|sequential",
      "calls": [{{
        "id": "unique_call_id",
        "role": "role",
        "objective": "bounded task instruction",
        "inputs": ["champion_engine"],
        "output_type": "analysis|engine"
      }}]
    }}],
    "final_call_id": "engine_call_id"
  }},
  "compliance": {{
    "changes_model_or_effort": false,
    "changes_benchmark_or_promotion": false,
    "tunes_engine_hyperparameters_as_structure": false,
    "hardcodes_benchmark": false
  }}
}}

STATE_CAPSULE={canonical_json(capsule)}
"""


class Architect:
    def __init__(self, client: CodexModelClient) -> None:
        self.client = client

    @property
    def policy_identity(self) -> dict[str, Any] | None:
        policy = getattr(self.client, "policy", None)
        if not isinstance(policy, ProposalPolicy):
            return None
        return proposal_policy_identity(policy)

    def propose(self, *, capsule: dict[str, Any], round_dir: Path) -> LoopPlan:
        generation_dir = round_dir / "generation"
        generation_dir.mkdir(parents=True, exist_ok=True)
        policy_identity = self.policy_identity
        policy_sha256 = content_hash(policy_identity) if policy_identity is not None else None
        session_path = generation_dir / "architect-session.json"
        if policy_identity is not None:
            if session_path.is_file():
                session = read_json(session_path)
                if (
                    session.get("proposal_policy") != policy_identity
                    or session.get("proposal_policy_sha256") != policy_sha256
                ):
                    raise RuntimeError(
                        "architect policy provenance does not match the active independent subagent"
                    )
            elif any(generation_dir.iterdir()):
                raise RuntimeError(
                    "architect policy provenance is missing from an existing partial generation"
                )
            else:
                atomic_json(
                    session_path,
                    {
                        "schema_version": 1,
                        "agent_role": "structural_architect",
                        "proposal_policy": policy_identity,
                        "proposal_policy_sha256": policy_sha256,
                    },
                )
        attempts_dir = generation_dir / "attempts"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        search_control = capsule.get("search_control", {})
        max_attempts = max(1, int(search_control.get("proposal_validation_max_attempts", 2)))
        validation_feedback = ""
        errors: list[str] = []

        for attempt_index in range(1, max_attempts + 1):
            attempt_dir = attempts_dir / f"attempt-{attempt_index:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = attempt_dir / "architect-prompt.txt"
            response_path = attempt_dir / "architect-response.txt"
            receipt_path = attempt_dir / "architect-receipt.json"
            error_path = attempt_dir / "validation-error.txt"

            if response_path.is_file() and receipt_path.is_file():
                receipt = read_json(receipt_path)
                if (
                    policy_sha256 is not None
                    and receipt.get("proposal_policy_sha256") != policy_sha256
                ):
                    raise RuntimeError(
                        "architect policy provenance does not match an existing proposal attempt"
                    )
                prompt = (
                    prompt_path.read_text(encoding="utf-8")
                    if prompt_path.is_file()
                    else architect_prompt(capsule, validation_feedback=validation_feedback)
                )
                response_text = response_path.read_text(encoding="utf-8")
            else:
                prompt = architect_prompt(capsule, validation_feedback=validation_feedback)
                prompt_path.write_text(prompt, encoding="utf-8")
                response = self.client.complete(
                    role="Sol max independent structural-architect subagent",
                    prompt=prompt,
                    working_directory=round_dir.parents[1],
                    allow_workspace_read=True,
                )
                response_text = response.text
                response_path.write_text(response_text, encoding="utf-8")
                atomic_json(
                    receipt_path,
                    {
                        "attempt": attempt_index,
                        **(
                            {
                                "agent_role": "structural_architect",
                                "proposal_policy": policy_identity,
                                "proposal_policy_sha256": policy_sha256,
                            }
                            if policy_identity is not None
                            else {}
                        ),
                        "prompt_sha256": content_hash(prompt),
                        "response_sha256": content_hash(response_text),
                        "usage": response.usage,
                        "trace_refs": list(response.trace_refs),
                    },
                )

            try:
                payload = parse_json_object(extract_final_answer(response_text))
                plan = LoopPlan.from_payload(
                    payload,
                    expected_mode=str(search_control["proposal_mode"]),
                )
                plan.validate_search_context(capsule)
            except (KeyError, TypeError, ValueError) as exc:
                validation_feedback = f"{type(exc).__name__}: {exc}"
                errors.append(validation_feedback)
                error_path.write_text(validation_feedback + "\n", encoding="utf-8")
                continue

            (generation_dir / "architect-prompt.txt").write_text(prompt, encoding="utf-8")
            (generation_dir / "architect-response.txt").write_text(response_text, encoding="utf-8")
            atomic_json(generation_dir / "architect-receipt.json", read_json(receipt_path))
            atomic_json(generation_dir / "normalized-plan.json", plan.payload)
            return plan

        raise PlanValidationError(
            f"architect exhausted {max_attempts} validation attempts: {' | '.join(errors)}"
        )


def _call_prompt(
    *,
    call: dict[str, Any],
    inputs: dict[str, str],
    output_type: str,
) -> str:
    search_rule = (
        "General internet search is allowed for this official Direct control, but benchmark cases, evaluator "
        "internals, and copied benchmark-specific answers remain forbidden."
        if call.get("allow_search") is True
        else "Do not use web search."
    )
    contract = (
        'Return exactly one JSON object and no prose: {"files":{"engine.py":"<complete Python source>"}}. '
        "Return a complete file, not a patch. The engine must obey the supplied task boundary."
        if output_type == "engine"
        else (
            "Return a compact evidence artifact for downstream calls. Do not emit an engine unless the objective "
            "asks for one."
        )
    )
    blocks = "\n\n".join(f"===== INPUT {name} =====\n{value}" for name, value in inputs.items())
    return f"""You are one call inside an evolved chess-engine construction loop.

ROLE: {call['role']}
OBJECTIVE: {call['objective']}

Follow only the declared information flow. You may use the isolated arm workspace and command tools to develop and
check scratch code. Use only general development evidence such as parsing, UCI handshake, legal-move behavior, perft,
determinism, timeouts, and task-general regression checks. The official ChessBench openings, match results, evaluator
internals, other repositories, and external files are unavailable and must not be sought. {search_rule} Work
from the supplied inputs and isolated workspace. Preserve working anchor behavior unless concrete evidence justifies a
change. Repair or roll back a locally failing edit before returning. {contract}

{blocks}
"""


class LoopExecutor:
    def __init__(self, client: CodexModelClient) -> None:
        self.client = client

    def execute(
        self,
        *,
        plan: LoopPlan,
        round_dir: Path,
        builtins: dict[str, str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        runtime_policy = getattr(self.client, "policy", None)
        if not isinstance(runtime_policy, RuntimePolicy):
            raise RuntimeError("loop execution requires a provenanced RuntimePolicy")
        runtime_policy.validate()
        outputs: dict[str, str] = {}
        traces: list[dict[str, Any]] = []
        calls_dir = round_dir / "execution" / "calls"
        calls_dir.mkdir(parents=True, exist_ok=True)

        for stage_index, stage in enumerate(plan.structure["stages"]):
            calls = list(stage["calls"])
            available = {**builtins, **outputs}

            def run_one(
                call_index: int,
                call: dict[str, Any],
                available_inputs: dict[str, str] = available,
                current_stage_index: int = stage_index,
            ) -> tuple[int, str, ModelCall, str]:
                selected = {str(name): available_inputs[str(name)] for name in call["inputs"]}
                prompt = _call_prompt(
                    call=call,
                    inputs=selected,
                    output_type=str(call["output_type"]),
                )
                prefix = f"{current_stage_index + 1:02d}-{call_index + 1:02d}-{call['id']}"
                (calls_dir / f"{prefix}.prompt.txt").write_text(prompt, encoding="utf-8")
                result = self.client.complete(
                    role=str(call["role"]),
                    prompt=prompt,
                    working_directory=round_dir,
                    allow_workspace_read=True,
                    allow_search=bool(call.get("allow_search", False)),
                )
                (calls_dir / f"{prefix}.response.txt").write_text(result.text, encoding="utf-8")
                return call_index, prefix, result, prompt

            completed: list[tuple[int, str, ModelCall, str]] = []
            if stage["mode"] == "parallel" and len(calls) > 1:
                with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                    future_map = {pool.submit(run_one, index, call): index for index, call in enumerate(calls)}
                    for future in as_completed(future_map):
                        completed.append(future.result())
            else:
                completed = [run_one(index, call) for index, call in enumerate(calls)]

            for call_index, prefix, result, prompt in sorted(completed):
                call = calls[call_index]
                output = result.text.strip()
                outputs[str(call["id"])] = output
                trace = {
                    "stage": str(stage["id"]),
                    "stage_mode": str(stage["mode"]),
                    "call_id": str(call["id"]),
                    "role": str(call["role"]),
                    "output_type": str(call["output_type"]),
                    "prompt_sha256": content_hash(prompt),
                    "response_sha256": content_hash(output),
                    "model": runtime_policy.model,
                    "reasoning_effort": runtime_policy.reasoning_effort,
                    "service_tier": runtime_policy.service_tier,
                    "request_tier": runtime_policy.request_tier,
                    "tier_contract": runtime_policy.tier_contract,
                    "runtime_policy_sha256": content_hash(runtime_policy_identity(runtime_policy)),
                    "usage": result.usage,
                    "trace_refs": list(result.trace_refs),
                }
                traces.append(trace)
                atomic_json(calls_dir / f"{prefix}.receipt.json", trace)

        final_raw = outputs[str(plan.structure["final_call_id"])]
        final_payload = parse_json_object(extract_final_answer(final_raw))
        files = final_payload.get("files")
        if not isinstance(files, dict) or set(files) != {"engine.py"} or not isinstance(files["engine.py"], str):
            raise ValueError("final loop call did not produce exactly files.engine.py")
        artifact_path = round_dir / "artifact" / "final-output.json"
        atomic_json(artifact_path, {"files": {"engine.py": files["engine.py"]}})
        return {"artifact_path": str(artifact_path.resolve()), "payload": final_payload}, traces


def load_architect(policy_path: Path) -> Architect:
    return Architect(CodexModelClient(ProposalPolicy.load(policy_path)))


def load_executor(policy_path: Path) -> LoopExecutor:
    return LoopExecutor(CodexModelClient(RuntimePolicy.load(policy_path)))

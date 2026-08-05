from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from loop_evolution.platform.backends.codex import CodexBackend
from loop_evolution.platform.config import ProposalPolicy, RuntimePolicy
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
    if mode == "counter_hypothesis":
        mode_instruction = (
            "COUNTER-HYPOTHESIS MODE persists until promotion. Identify the dominant assumption behind the current "
            "search direction, invert it, and fill hypothesis.dominant_assumption and hypothesis.inversion. The "
            "inversion may switch collaboration to solo or solo to collaboration, but it may instead invert another "
            "evidenced dominant assumption."
        )
        emergent_schema = ""
    elif mode == "emergent_exploration":
        mode_instruction = (
            "EMERGENT-EXPLORATION MODE. Preserve supported champion strengths but enable one observable action that "
            "the champion's current control flow cannot perform. A larger packet, an extra certificate field, a "
            "moved audit, a finer rollback scope, a renamed ledger, or an added reviewer/gate is not emergent unless "
            "it creates a genuinely new trigger-dependent state transition and decision path. Derive the capability "
            "from the evidence rather than choosing from a fixed menu. Do not merely repair the previous emergent "
            "attempt. If search_control lists a previously tested emergent capability family, choose a different "
            "family. Fill hypothesis.emergent_capability completely and make its novelty_probe executable or "
            "otherwise concretely observable."
        )
        emergent_schema = '''
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
        mode_instruction = (
            "LOCAL-REFINEMENT MODE. Make one evidence-led causal refinement while preserving the champion's macro "
            "capability family. This round counts toward the two-round local budget whether or not it promotes. Do "
            "not fill dominant_assumption or inversion merely for novelty."
        )
        emergent_schema = ""
    retry_instruction = (
        "\nThe preceding proposal was rejected before evaluation. Correct the stated contract violation while "
        f"still proposing one coherent candidate. VALIDATION_FEEDBACK={validation_feedback}\n"
        if validation_feedback
        else ""
    )
    return f"""You are the single Sol xhigh architect evolving a loop structure, not a chess engine.

The current champion is one indivisible package: loop structure plus the engine that structure produced. Propose one
new loop structure that will start from the champion anchor engine and attempt to produce a stronger engine. The
candidate and current champion structures will each run from the exact same anchor in three matched pairs. Their final
engines are evaluated by the frozen ChessBench; promotion requires paired superiority, candidate-median superiority,
and zero invalid candidate arms. The precommitted median-ranked candidate engine represents a winning batch. Solo and
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
{emergent_schema}
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

    def propose(self, *, capsule: dict[str, Any], round_dir: Path) -> LoopPlan:
        generation_dir = round_dir / "generation"
        generation_dir.mkdir(parents=True, exist_ok=True)
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
                    role="Sol xhigh causal loop-structure architect",
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

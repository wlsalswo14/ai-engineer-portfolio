from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primus.errors import BackendError, QuotaUnavailable
from primus.jsonutil import atomic_json, bytes_hash, utc_now
from primus.models import ModelPolicy, Usage


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: Usage
    raw_events: str
    home_slot: int
    web_search_calls: int


class CodexBackend:
    """Subscription-only Codex executor with bounded, auditable retries."""

    def __init__(
        self,
        policy: ModelPolicy,
        *,
        retry_attempts: int = 2,
        retry_delay_seconds: float = 3.0,
        allow_web_search: bool = False,
    ):
        self.policy = policy
        self.retry_attempts = retry_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.allow_web_search = allow_web_search
        self._next_home = 0

    def _launcher(self) -> tuple[str, ...]:
        executable = self.policy.codex_executable
        if os.name != "nt" or not executable.lower().endswith((".cmd", ".bat")):
            resolved = shutil.which(executable) or executable
            return (resolved,)
        wrapper = shutil.which(executable)
        node = shutil.which("node")
        if not wrapper or not node:
            raise BackendError(f"Codex launcher is unavailable: {executable}")
        script = Path(wrapper).resolve().parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if not script.is_file():
            raise BackendError(f"Codex JavaScript launcher is unavailable: {script}")
        return node, str(script)

    def _command(self, working_directory: Path) -> tuple[str, ...]:
        search_options = ("--search",) if self.allow_web_search else ("--config", 'web_search="disabled"')
        return (
            *self._launcher(),
            *search_options,
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--strict-config",
            "--config",
            f'service_tier="{self.policy.service_tier}"',
            "--skip-git-repo-check",
            "--model",
            self.policy.model,
            "--config",
            f'model_reasoning_effort="{self.policy.reasoning_effort}"',
            "--sandbox",
            "workspace-write",
            "--cd",
            str(working_directory.resolve()),
            "-",
        )

    def complete(
        self,
        *,
        role: str,
        prompt: str,
        working_directory: Path,
        receipt_dir: Path,
        timeout_seconds: float | None = None,
    ) -> ModelResponse:
        working_directory.mkdir(parents=True, exist_ok=True)
        request = f"Role: {role}\n\n{prompt}"
        deadline = time.monotonic() + (
            float(timeout_seconds) if timeout_seconds is not None else float(self.policy.max_wall_seconds)
        )
        homes = self.policy.codex_home_pool or (str(os.environ.get("CODEX_HOME", "")),)
        attempts: list[dict[str, Any]] = []
        last_error = ""
        for offset in range(len(homes)):
            slot = (self._next_home + offset) % len(homes)
            environment = os.environ.copy()
            if homes[slot]:
                environment["CODEX_HOME"] = homes[slot]
            for attempt in range(1, self.retry_attempts + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    last_error = "timeout"
                    attempts.append({"home_slot": slot, "attempt": attempt, "status": "budget_timeout"})
                    break
                started = time.monotonic()
                try:
                    completed = subprocess.run(
                        self._command(working_directory),
                        input=request,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        capture_output=True,
                        shell=False,
                        timeout=min(float(self.policy.max_wall_seconds), remaining),
                        env=environment,
                    )
                except subprocess.TimeoutExpired as exc:
                    last_error = "timeout"
                    attempts.append({"home_slot": slot, "attempt": attempt, "status": "timeout"})
                    if attempt < self.retry_attempts:
                        time.sleep(min(self.retry_delay_seconds, max(0.0, deadline - time.monotonic())))
                        continue
                    break
                duration = time.monotonic() - started
                combined = f"{completed.stdout}\n{completed.stderr}".casefold()
                attempts.append(
                    {
                        "home_slot": slot,
                        "attempt": attempt,
                        "returncode": completed.returncode,
                        "duration_seconds": duration,
                        "stdout_sha256": bytes_hash(completed.stdout.encode("utf-8")),
                        "stderr_sha256": bytes_hash(completed.stderr.encode("utf-8")),
                    }
                )
                if completed.returncode != 0:
                    last_error = completed.stderr.strip() or "codex execution failed"
                    if any(marker in combined for marker in ("quota", "usage limit", "rate limit")):
                        break
                    if any(marker in combined for marker in ("connection reset", "reconnecting", "temporarily unavailable")) and attempt < self.retry_attempts:
                        time.sleep(min(self.retry_delay_seconds, max(0.0, deadline - time.monotonic())))
                        continue
                    self._write_failure_receipt(receipt_dir, request, attempts, last_error)
                    raise BackendError(last_error)
                response = self._parse(completed.stdout, slot)
                receipt_dir.mkdir(parents=True, exist_ok=True)
                (receipt_dir / "raw-events.jsonl").write_text(completed.stdout, encoding="utf-8")
                (receipt_dir / "prompt.txt").write_text(request, encoding="utf-8")
                (receipt_dir / "response.txt").write_text(response.text, encoding="utf-8")
                atomic_json(
                    receipt_dir / "receipt.json",
                    {
                        "schema_version": 1,
                        "created_at": utc_now(),
                        "model": self.policy.model,
                        "reasoning_effort": self.policy.reasoning_effort,
                        "service_tier": self.policy.service_tier,
                        "request_tier": self.policy.request_tier,
                        "web_search_enabled": self.allow_web_search,
                        "web_search_calls": response.web_search_calls,
                        "home_slot": slot,
                        "prompt_sha256": bytes_hash(request.encode("utf-8")),
                        "response_sha256": bytes_hash(response.text.encode("utf-8")),
                        "raw_events_sha256": bytes_hash(completed.stdout.encode("utf-8")),
                        "usage": response.usage.to_dict(),
                        "attempts": attempts,
                        "execution_directory": str(working_directory.resolve()),
                    },
                )
                self._next_home = slot
                return response
        self._write_failure_receipt(receipt_dir, request, attempts, last_error or "quota unavailable")
        raise QuotaUnavailable("all configured subscription homes are quota unavailable")

    @staticmethod
    def _parse(payload: str, slot: int) -> ModelResponse:
        messages: list[str] = []
        usage = Usage(model_calls=1)
        web_search_calls = 0
        for line in payload.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BackendError("Codex returned non-JSONL output") from exc
            kind = str(event.get("type", ""))
            if kind == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message" and item.get("text"):
                    messages.append(str(item["text"]))
                elif "web_search" in str(item.get("type", "")):
                    web_search_calls += 1
            elif kind == "turn.completed":
                raw = event.get("usage", {})
                usage = Usage(
                    input_tokens=int(raw.get("input_tokens", 0)),
                    cached_input_tokens=int(raw.get("cached_input_tokens", 0)),
                    output_tokens=int(raw.get("output_tokens", 0)),
                    reasoning_output_tokens=int(raw.get("reasoning_output_tokens", 0)),
                    model_calls=1,
                )
            elif kind in {"turn.failed", "error"}:
                raise BackendError(str(event.get("message") or event.get("error") or "Codex turn failed"))
        if not messages:
            raise BackendError("Codex completed without an agent message")
        return ModelResponse(messages[-1], usage, payload, slot, web_search_calls)

    @staticmethod
    def _write_failure_receipt(receipt_dir: Path, request: str, attempts: list[dict[str, Any]], error: str) -> None:
        receipt_dir.mkdir(parents=True, exist_ok=True)
        (receipt_dir / "prompt.txt").write_text(request, encoding="utf-8")
        atomic_json(
            receipt_dir / "failure-receipt.json",
            {
                "schema_version": 1,
                "created_at": utc_now(),
                "prompt_sha256": bytes_hash(request.encode("utf-8")),
                "attempts": attempts,
                "error": error,
            },
        )

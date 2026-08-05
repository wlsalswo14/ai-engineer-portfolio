from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from loop_evolution.platform.backends.process import CommandResult, CommandRunner, SubprocessCommandRunner
from loop_evolution.platform.config import ProposalPolicy, RuntimePolicy
from loop_evolution.platform.domain import ModelUsage
from loop_evolution.platform.interfaces import ModelResponse


class CodexBackendError(RuntimeError):
    pass


class CodexTransientError(CodexBackendError):
    """A temporary transport failure that is safe to retry with the same request."""


class CodexQuotaUnavailable(CodexBackendError):
    pass


class CodexAuthenticationError(CodexBackendError):
    pass


class CodexExecutionTimeout(CodexBackendError):
    pass


_TRANSIENT_ERROR_MARKERS = (
    "connection aborted",
    "connection refused",
    "connection reset",
    "dns",
    "name resolution",
    "network is unreachable",
    "os error 10054",
    "os error 11001",
    "reconnecting",
    "stream disconnected",
    "temporarily unavailable",
    "temporary failure",
)


def _is_transient_error(message: str) -> bool:
    normalized = message.casefold()
    return any(marker in normalized for marker in _TRANSIENT_ERROR_MARKERS)


@dataclass(frozen=True)
class CodexRetryPolicy:
    """Bounded retries for transport failures within one model-call wall budget."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 4.0

    def validate(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("Codex retry attempts must be positive")
        if min(self.initial_backoff_seconds, self.max_backoff_seconds) < 0:
            raise ValueError("Codex retry backoff cannot be negative")
        if self.initial_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("initial Codex retry backoff cannot exceed the maximum")

    def delay_before_attempt(self, attempt: int) -> float:
        """Return the delay before a 1-based retry attempt (attempt >= 2)."""
        if attempt < 2:
            return 0.0
        return min(
            self.initial_backoff_seconds * (2 ** (attempt - 2)),
            self.max_backoff_seconds,
        )


@dataclass(frozen=True)
class CodexCommandBuilder:
    policy: RuntimePolicy | ProposalPolicy

    def launcher(self) -> tuple[str, ...]:
        executable = self.policy.codex_executable
        if os.name != "nt" or not executable.lower().endswith((".cmd", ".bat")):
            return (executable,)

        wrapper = shutil.which(executable)
        if wrapper is None:
            raise CodexBackendError(f"Codex launcher was not found: {executable}")
        wrapper_path = Path(wrapper).resolve()
        node = shutil.which("node")
        script = wrapper_path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if node is None or not script.is_file():
            raise CodexBackendError("native Windows Codex launch prerequisites were not found")
        return (node, str(script))

    def build(
        self,
        *,
        prompt: str,
        working_directory: str,
        allowed_tools: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        self.policy.validate()
        unsupported = set(allowed_tools) - {"search", "workspace_read", "command"}
        if unsupported:
            raise CodexBackendError(f"unsupported Codex tool classes: {sorted(unsupported)}")
        search_options = ("--search",) if "search" in allowed_tools else ("--config", 'web_search="disabled"')
        return (
            *self.launcher(),
            *search_options,
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--model",
            self.policy.model,
            "--config",
            f'model_reasoning_effort="{self.policy.reasoning_effort}"',
            "--sandbox",
            self.policy.sandbox,
            "--cd",
            working_directory,
            "-",
        )


@dataclass
class CodexBackend:
    policy: RuntimePolicy | ProposalPolicy
    runner: CommandRunner = field(default_factory=SubprocessCommandRunner)
    retry_policy: CodexRetryPolicy = field(default_factory=CodexRetryPolicy)
    sleeper: Callable[[float], None] = field(default=time.sleep, repr=False)
    _authenticated_homes: set[str] = field(default_factory=set, init=False)
    _invalid_homes: set[str] = field(default_factory=set, init=False)
    _home_index: int = field(default=0, init=False)

    def complete(self, *, role: str, prompt: str, working_directory: str) -> ModelResponse:
        return self.complete_with_timeout(
            role=role,
            prompt=prompt,
            working_directory=working_directory,
            timeout_seconds=self.policy.max_wall_seconds,
        )

    def complete_with_timeout(
        self,
        *,
        role: str,
        prompt: str,
        working_directory: str,
        timeout_seconds: float,
    ) -> ModelResponse:
        return self.complete_with_tools(
            role=role,
            prompt=prompt,
            working_directory=working_directory,
            allowed_tools=(),
            timeout_seconds=timeout_seconds,
        )

    def complete_with_tools(
        self,
        *,
        role: str,
        prompt: str,
        working_directory: str,
        allowed_tools: tuple[str, ...],
        timeout_seconds: float,
    ) -> ModelResponse:
        self.policy.validate_live_environment()
        self.retry_policy.validate()
        instruction = f"Role: {role}\n\n{prompt}"
        command = CodexCommandBuilder(self.policy).build(
            prompt=instruction,
            working_directory=working_directory,
            allowed_tools=allowed_tools,
        )
        wall_budget = min(timeout_seconds, self.policy.max_wall_seconds)
        deadline = time.monotonic() + wall_budget
        homes = self._subscription_homes()
        last_quota: CodexQuotaUnavailable | None = None
        last_authentication: CodexAuthenticationError | None = None
        start_home_index = self._home_index
        for home_offset in range(len(homes)):
            home_index = (start_home_index + home_offset) % len(homes)
            home = homes[home_index]
            authentication_key = home or "<inherited>"
            if authentication_key in self._invalid_homes:
                continue
            environment = self._environment_for_home(home)
            try:
                self._verify_subscription_authentication(home, environment)
            except CodexAuthenticationError as exc:
                last_authentication = exc
                self._invalid_homes.add(authentication_key)
                continue
            for attempt in range(1, self.retry_policy.max_attempts + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexExecutionTimeout(
                        "Codex execution exceeded the manifest wall-time budget"
                    )
                try:
                    result = self.runner.run(
                        command,
                        timeout_seconds=remaining,
                        input_text=instruction,
                        environment=environment,
                    )
                    response = self._response_from_result(result)
                    self._home_index = home_index
                    return ModelResponse(
                        text=response.text,
                        usage=response.usage,
                        trace_refs=(
                            *response.trace_refs,
                            f"codex-subscription-home-slot:{home_index}",
                        ),
                    )
                except subprocess.TimeoutExpired as exc:
                    raise CodexExecutionTimeout(
                        "Codex execution exceeded the manifest wall-time budget"
                    ) from exc
                except CodexQuotaUnavailable as exc:
                    last_quota = exc
                    self._home_index = (home_index + 1) % len(homes)
                    break
                except CodexAuthenticationError as exc:
                    last_authentication = exc
                    self._authenticated_homes.discard(authentication_key)
                    self._invalid_homes.add(authentication_key)
                    self._home_index = (home_index + 1) % len(homes)
                    break
                except CodexTransientError as exc:
                    if attempt >= self.retry_policy.max_attempts:
                        raise
                    delay = self.retry_policy.delay_before_attempt(attempt + 1)
                    if delay >= deadline - time.monotonic():
                        raise CodexExecutionTimeout(
                            "Codex transient retries exhausted the manifest wall-time budget"
                        ) from exc
                    self.sleeper(delay)
        if last_quota is not None:
            raise last_quota
        if last_authentication is not None:
            raise last_authentication
        raise CodexAuthenticationError("no valid ChatGPT subscription home is available")

    def _response_from_result(self, result: CommandResult) -> ModelResponse:
        stdout = result.stdout
        stderr = result.stderr
        returncode = result.returncode
        combined_error = f"{stderr}\n{stdout}".casefold()
        if returncode != 0:
            if any(
                token in combined_error
                for token in (
                    "401 unauthorized",
                    "refresh_token_invalidated",
                    "token_invalidated",
                    "your session has ended",
                )
            ):
                raise CodexAuthenticationError(
                    "Codex ChatGPT subscription authentication is invalid"
                )
            if any(token in combined_error for token in ("quota", "usage limit", "rate limit")):
                raise CodexQuotaUnavailable("Codex quota is unavailable")
            message = stderr.strip() or f"codex exec exited with {returncode}"
            if _is_transient_error(combined_error):
                raise CodexTransientError(message)
            raise CodexBackendError(message)
        return self._parse_jsonl(stdout)

    def _verify_subscription_authentication(
        self,
        home: str,
        environment: dict[str, str],
    ) -> None:
        authentication_key = home or "<inherited>"
        if authentication_key in self._authenticated_homes:
            return
        result = self.runner.run(
            (*CodexCommandBuilder(self.policy).launcher(), "login", "status"),
            timeout_seconds=15,
            environment=environment,
        )
        status = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 or "ChatGPT" not in status:
            raise CodexAuthenticationError("Codex must be logged in using ChatGPT subscription authentication")
        self._authenticated_homes.add(authentication_key)

    def _subscription_homes(self) -> tuple[str, ...]:
        configured = tuple(str(item) for item in self.policy.codex_home_pool)
        if configured:
            return configured
        return (str(os.environ.get("CODEX_HOME", "")),)

    @staticmethod
    def _environment_for_home(home: str) -> dict[str, str]:
        environment = os.environ.copy()
        if home:
            environment["CODEX_HOME"] = home
        return environment

    @staticmethod
    def _parse_jsonl(payload: str) -> ModelResponse:
        messages: list[str] = []
        traces: list[str] = []
        usage = ModelUsage()
        for raw_line in payload.splitlines():
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise CodexBackendError("codex exec returned non-JSON output") from exc
            event_type = str(event.get("type", ""))
            traces.append(event_type)
            if event_type == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message" and item.get("text"):
                    messages.append(str(item["text"]))
            elif event_type == "turn.completed":
                raw_usage = event.get("usage", {})
                usage = ModelUsage(
                    input_tokens=int(raw_usage.get("input_tokens", 0)),
                    cached_input_tokens=int(raw_usage.get("cached_input_tokens", 0)),
                    output_tokens=int(raw_usage.get("output_tokens", 0)),
                    reasoning_output_tokens=int(raw_usage.get("reasoning_output_tokens", 0)),
                    model_calls=1,
                )
            elif event_type in {"turn.failed", "error"}:
                message = str(event.get("message") or event.get("error") or "Codex turn failed")
                if "quota" in message.lower() or "usage limit" in message.lower():
                    raise CodexQuotaUnavailable(message)
                if _is_transient_error(message):
                    raise CodexTransientError(message)
                raise CodexBackendError(message)
        if not messages:
            raise CodexBackendError("codex exec completed without an agent message")
        return ModelResponse(text=messages[-1], usage=usage, trace_refs=tuple(traces))

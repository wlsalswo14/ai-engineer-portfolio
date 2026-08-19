from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
        input_text: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
        input_text: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        process_environment = None
        if environment is not None:
            process_environment = dict(environment)
        completed = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=process_environment,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

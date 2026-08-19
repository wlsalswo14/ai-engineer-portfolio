from __future__ import annotations

import ctypes
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from loop_evolution.common import atomic_json, canonical_json, read_json


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RoundCampaign:
    """Run one persisted evolution round at a time until a display-round target."""

    def __init__(
        self,
        pipeline: Any,
        *,
        target_display_round: int,
        retry_delay_seconds: float = 30,
        sleep: Callable[[float], None] = time.sleep,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if target_display_round < 0:
            raise ValueError("target display round must be non-negative")
        if not 0 <= retry_delay_seconds <= 60:
            raise ValueError("retry delay must be between 0 and 60 seconds")
        self.pipeline = pipeline
        self.workspace = Path(pipeline.workspace)
        self.target_display_round = int(target_display_round)
        self.retry_delay_seconds = float(retry_delay_seconds)
        self.sleep = sleep
        self.emit = emit or (lambda event: print(canonical_json(event), flush=True))
        self.control_path = self.workspace / "campaign-control.json"
        self.events_path = self.workspace / "campaign-events.jsonl"
        self.lock_path = self.workspace / "campaign.lock.json"
        self.run_id = uuid4().hex
        self._lock_owned = False

    @property
    def display_offset(self) -> int:
        return int(self.pipeline.config.get("display_round_offset", 0))

    @property
    def target_internal_round(self) -> int:
        return self.target_display_round - self.display_offset

    def _display_round(self, internal_round: int) -> int:
        return internal_round + self.display_offset

    def _state(self) -> dict[str, Any]:
        return self.pipeline.store.migrate_to_matched_pairs()

    def _append_event(self, event: dict[str, Any]) -> None:
        payload = {"timestamp": _timestamp(), "run_id": self.run_id, **event}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.emit(payload)

    def _write_control(
        self,
        *,
        status: str,
        internal_round: int,
        consecutive_errors: int = 0,
        last_error: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        control: dict[str, Any] = {
            "schema_version": 1,
            "run_id": self.run_id,
            "pid": os.getpid(),
            "status": status,
            "updated_at": _timestamp(),
            "target_display_round": self.target_display_round,
            "target_internal_round": self.target_internal_round,
            "internal_round": internal_round,
            "display_round": self._display_round(internal_round),
            "consecutive_errors": consecutive_errors,
            "single_experiment_only": True,
            "early_adjudication": not bool(
                getattr(self.pipeline, "force_complete_pairs", False)
            ),
        }
        if last_error:
            control["last_error"] = last_error
        atomic_json(self.control_path, control)
        return control

    def _acquire_lock(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.lock_path.is_file():
            try:
                existing = read_json(self.lock_path)
            except (OSError, ValueError, json.JSONDecodeError):
                existing = {}
            existing_pid = int(existing.get("pid", 0) or 0)
            if _pid_is_alive(existing_pid):
                raise RuntimeError(
                    f"another campaign is active: pid={existing_pid}, "
                    f"run_id={existing.get('run_id', 'unknown')}"
                )
            stale_dir = self.workspace / "archive" / "stale-campaign-locks"
            stale_dir.mkdir(parents=True, exist_ok=True)
            stale_path = stale_dir / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex}.json"
            os.replace(self.lock_path, stale_path)
        descriptor = os.open(
            self.lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(
                descriptor,
                (canonical_json({"pid": os.getpid(), "run_id": self.run_id}) + "\n").encode(
                    "utf-8"
                ),
            )
        finally:
            os.close(descriptor)
        self._lock_owned = True

    def _release_lock(self) -> None:
        if not self._lock_owned:
            return
        try:
            existing = read_json(self.lock_path)
            if existing.get("run_id") == self.run_id:
                self.lock_path.unlink(missing_ok=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        self._lock_owned = False

    def _recover_committed_round(self, before_round: int, after_round: int) -> None:
        if after_round <= before_round or not hasattr(self.pipeline, "recover_round"):
            return
        try:
            self.pipeline.recover_round()
        except RuntimeError:
            # A fully finalized round correctly has nothing left to recover.
            return

    def run(self) -> dict[str, Any]:
        self._acquire_lock()
        try:
            state = self._state()
            current = int(state["round_index"])
            current_display = self._display_round(current)
            if self.target_display_round < current_display:
                raise ValueError(
                    f"target display round {self.target_display_round} is behind current "
                    f"display round {current_display}"
                )
            self._write_control(status="running", internal_round=current)
            self._append_event(
                {
                    "event": "campaign_started",
                    "internal_round": current,
                    "display_round": current_display,
                    "target_display_round": self.target_display_round,
                }
            )
            consecutive_errors = 0
            while current < self.target_internal_round:
                before = current
                try:
                    result = self.pipeline.run_round()
                    state = self._state()
                    current = int(state["round_index"])
                    if current != before + 1:
                        raise RuntimeError(
                            "one campaign iteration must advance exactly one internal round: "
                            f"before={before}, after={current}"
                        )
                except KeyboardInterrupt:
                    current = int(self._state()["round_index"])
                    self._write_control(status="stopped_by_operator", internal_round=current)
                    self._append_event(
                        {
                            "event": "campaign_stopped_by_operator",
                            "internal_round": current,
                            "display_round": self._display_round(current),
                        }
                    )
                    raise
                except Exception as exc:  # keep long campaigns alive across transient failures
                    after = int(self._state()["round_index"])
                    self._recover_committed_round(before, after)
                    if after > before:
                        current = after
                        consecutive_errors = 0
                        self._write_control(status="running", internal_round=current)
                        self._append_event(
                            {
                                "event": "round_committed_after_exception",
                                "internal_round": current,
                                "display_round": self._display_round(current),
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            }
                        )
                        continue
                    consecutive_errors += 1
                    error = {"type": type(exc).__name__, "message": str(exc)}
                    self._write_control(
                        status="retrying",
                        internal_round=before,
                        consecutive_errors=consecutive_errors,
                        last_error=error,
                    )
                    self._append_event(
                        {
                            "event": "round_failed_will_retry",
                            "internal_round": before + 1,
                            "display_round": self._display_round(before + 1),
                            "consecutive_errors": consecutive_errors,
                            "retry_delay_seconds": self.retry_delay_seconds,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    self.sleep(self.retry_delay_seconds)
                    current = int(self._state()["round_index"])
                    continue

                consecutive_errors = 0
                self._write_control(status="running", internal_round=current)
                self._append_event(
                    {
                        "event": "round_completed",
                        "internal_round": current,
                        "display_round": self._display_round(current),
                        "promoted": bool(result.get("promoted", False)),
                        "completed_pair_count": result.get("batch_decision", {}).get(
                            "completed_pair_count"
                        ),
                        "completed_early": result.get("batch_decision", {}).get(
                            "completed_early"
                        ),
                        "champion_package_after": result.get("champion_package_after"),
                    }
                )

            control = self._write_control(status="completed", internal_round=current)
            self._append_event(
                {
                    "event": "campaign_completed",
                    "internal_round": current,
                    "display_round": self._display_round(current),
                    "target_display_round": self.target_display_round,
                }
            )
            return control
        finally:
            self._release_lock()

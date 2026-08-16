from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from primus.errors import LifecycleError
from primus.jsonutil import utc_now


class ExclusiveLease:
    def __init__(self, path: Path, *, owner: str, stale_after_seconds: int = 7200):
        self.path = path
        self.owner = owner
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    def __enter__(self) -> "ExclusiveLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "owner": self.owner,
            "pid": os.getpid(),
            "created_at": utc_now(),
            "created_epoch": time.time(),
        }
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    existing: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
                    stale = time.time() - float(existing.get("created_epoch", 0)) > self.stale_after_seconds
                    pid = int(existing.get("pid", 0))
                    alive = pid > 0
                    if alive and os.name == "nt":
                        import ctypes

                        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                        alive = bool(handle)
                        if handle:
                            ctypes.windll.kernel32.CloseHandle(handle)
                    if stale or not alive:
                        quarantine = self.path.with_name(f"{self.path.name}.stale-{int(time.time())}")
                        os.replace(self.path, quarantine)
                        continue
                except Exception:
                    pass
                raise LifecycleError(f"lease is already held: {self.path}")
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                self.acquired = True
                return self
        raise LifecycleError(f"could not acquire lease: {self.path}")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.acquired:
            try:
                current = json.loads(self.path.read_text(encoding="utf-8"))
                if current.get("owner") == self.owner and int(current.get("pid", -1)) == os.getpid():
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    request_path, result_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    runner_path = Path(request["runner_path"]).resolve()
    if sha256_file(runner_path) != request["runner_sha256"]:
        raise RuntimeError("cache runner digest mismatch")
    spec = importlib.util.spec_from_file_location("_primus_cache_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load cache runner")
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)
    traces = runner.generate_trace_suite(int(request["seed"]), int(request["scale"]))
    result = runner.evaluate_candidate(Path(request["policy_path"]), traces=traces, timeout_s=float(request["timeout_seconds"]))
    result_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

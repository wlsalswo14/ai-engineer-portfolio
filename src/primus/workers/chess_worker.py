from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    request_path, result_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    source_root = Path(request["ouroboros_source"]).resolve()
    sys.path.insert(0, str(source_root))
    from loop_evolution.platform.common import content_hash
    from loop_evolution.platform.domain import TaskCase
    from loop_evolution.platform.evaluation.chessbench import ChessBench100Scorer

    raw = request["case"]
    metadata = dict(raw["metadata"])
    metadata["result_dir"] = request["result_dir"]
    case = TaskCase(
        task_id=str(raw["id"]),
        family=str(raw["family"]),
        request=str(raw["request"]),
        expected=raw.get("expected"),
        scorer=str(raw["scorer"]),
        critical=bool(raw.get("critical", False)),
        metadata=metadata,
    )
    output = Path(request["artifact_path"]).read_text(encoding="utf-8")
    scorer = ChessBench100Scorer(result_cache_dir=Path(request["result_dir"]))
    if request["split"] == "development":
        public_score, public_failure, public_evidence = scorer.verify_public(output)
        if public_failure:
            result = {"score": None, "failure_kind": public_failure, "evidence": public_evidence}
        else:
            score, failure, evidence = scorer.score(case, output)
            result = {"score": score, "failure_kind": failure, "evidence": (*public_evidence, *evidence)}
    else:
        score, failure, evidence = scorer.score(case, output)
        result = {"score": score, "failure_kind": failure, "evidence": evidence}
    result["result_digest"] = content_hash(result)
    result_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

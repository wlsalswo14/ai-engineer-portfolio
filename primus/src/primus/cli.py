from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from primus.doctor import doctor, status
from primus.cost import pipeline_cost
from primus.errors import PrimusError
from primus.migration import migrate
from primus.orchestrator import PrimusOrchestrator
from primus.smoke import smoke
from primus.store import PrimusStore


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUROBOROS = Path("C:/Users/jinminjae/OneDrive/Desktop/Ouroboros/loop-evolution")
DEFAULT_ARCHIVE = Path("C:/Users/jinminjae/OneDrive/Desktop/loopsy_archive")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="primus", description="Production Lopvolution outer loop")
    result.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="initialize state, task banks, champions, and legacy registry")
    init.add_argument("--ouroboros", type=Path, default=DEFAULT_OUROBOROS)
    init.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    sub.add_parser("status", help="show configured active champions and rounds")
    sub.add_parser("doctor", help="verify executable, configs, task isolation, digests, DB, and receipts")
    sub.add_parser("smoke", help="execute configured real evaluator boundaries without model calls")
    cost = sub.add_parser("cost", help="show staged model-call and Chess-game costs")
    cost.add_argument("domain")
    cost.add_argument("--candidate-calls", type=int)
    audit = sub.add_parser("audit", help="verify the immutable registry and receipt chain")
    loop = sub.add_parser("loop", help="start or resume real rounds")
    loop.add_argument("action", choices=("start", "resume"))
    loop.add_argument("domain")
    loop.add_argument("--rounds", type=int, default=1)
    loop.add_argument("--run-id")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "init":
            payload = migrate(root, ouroboros=args.ouroboros, archive=args.archive)
        elif args.command == "status":
            payload = status(root)
        elif args.command == "doctor":
            payload = {"ok": True, "checks": doctor(root)}
        elif args.command == "smoke":
            payload = smoke(root)
        elif args.command == "cost":
            payload = pipeline_cost(root, args.domain, candidate_calls=args.candidate_calls)
        elif args.command == "audit":
            payload = {"ok": True, "checks": PrimusStore(root).audit()}
        elif args.command == "loop":
            orchestrator = PrimusOrchestrator(root)
            payload = None
            if args.action == "resume":
                run_id = args.run_id or (orchestrator.store.latest_round(args.domain, unfinished_only=True) or {}).get("run_id")
                if not run_id:
                    raise PrimusError(f"no unfinished round for {args.domain}")
                payload = orchestrator.resume(run_id)
            else:
                if args.rounds < 1:
                    raise PrimusError("--rounds must be positive")
                completed = []
                for _ in range(args.rounds):
                    completed.append(orchestrator.start(args.domain))
                payload = {"completed": completed}
        else:
            raise AssertionError(args.command)
    except (PrimusError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

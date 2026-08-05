from __future__ import annotations

import argparse
import json
from pathlib import Path

from loop_evolution.pipeline import EvolutionPipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evolve chess loop-structure and engine packages together.")
    parser.add_argument(
        "command",
        choices=(
            "init",
            "migrate",
            "status",
            "propose",
            "run-round",
            "run-fixed-round",
            "recover-round",
            "reconcile-round",
            "readjudicate-relative",
            "calibrate-direct",
            "abort-round",
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=(
            Path(__file__).resolve().parents[2]
            / "experiments"
            / "chess-tier5-clean"
            / "config.json"
        ),
    )
    parser.add_argument("--round", type=int)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--authoritative-record")
    parser.add_argument("--reason")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pipeline = EvolutionPipeline(args.config)
    if args.command == "init":
        result = pipeline.initialize()
    elif args.command == "migrate":
        result = pipeline.migrate()
    elif args.command == "status":
        result = pipeline.status()
    elif args.command == "propose":
        result = pipeline.propose().payload
    elif args.command == "run-round":
        result = pipeline.run_round()
    elif args.command == "run-fixed-round":
        if args.plan is None:
            raise SystemExit("run-fixed-round requires --plan")
        result = pipeline.run_fixed_round(args.plan)
    elif args.command == "recover-round":
        result = pipeline.recover_round()
    elif args.command == "reconcile-round":
        if args.round is None or not args.authoritative_record:
            raise SystemExit("reconcile-round requires --round and --authoritative-record")
        result = pipeline.reconcile_round(args.round, args.authoritative_record)
    elif args.command == "readjudicate-relative":
        if args.round is None:
            raise SystemExit("readjudicate-relative requires --round")
        result = pipeline.readjudicate_relative_promotion(args.round)
    elif args.command == "abort-round":
        if not args.reason:
            raise SystemExit("abort-round requires --reason")
        result = pipeline.abort_next_round(args.reason)
    else:
        result = pipeline.calibrate_direct()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$HERE/../runners/chess_engine_loop.py"
BENCH="$HERE"
MODE="${1:-smoke}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 2
fi

if ! python3 - <<'PY' >/dev/null 2>&1
import chess
PY
then
  echo "Python package 'chess' is required. Install with: python3 -m pip install chess==1.11.2" >&2
  exit 2
fi

case "$MODE" in
  smoke)
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    python3 "$RUNNER" write-random-engine --out "$work/engine.py" >/dev/null
    python3 "$RUNNER" evaluate-engine \
      --engine "$work/engine.py" \
      --suites mini_opening \
      --games-per-fen 1 \
      --movetime-ms 20 \
      --max-plies 12 \
      --stockfish-depth 1 \
      --stockfish-elo 1320
    ;;
  eval-included)
    engine="$BENCH/generated_engines/20260524/repeat_core_t2/gpt-5.5/cumulative_hidden_eval_loop/trial_01/round_01/engine.py"
    python3 "$RUNNER" evaluate-engine \
      --engine "$engine" \
      --suites opening_gauntlet advantage_conversion \
      --games-per-fen 1 \
      --movetime-ms 20 \
      --max-plies 40 \
      --stockfish-depth 1 \
      --stockfish-elo 1320
    ;;
  summary)
    python3 -m json.tool "$BENCH/results/20260524/summary.json"
    ;;
  *)
    echo "usage: $0 [smoke|eval-included|summary]" >&2
    exit 2
    ;;
esac

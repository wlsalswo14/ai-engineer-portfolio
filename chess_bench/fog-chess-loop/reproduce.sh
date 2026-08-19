#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT/runners/fog_chess_loop.py"
MODE="${1:-smoke}"

case "$MODE" in
  smoke)
    python3 "$RUNNER" smoke --out-dir "$ROOT/tmp/fog_chess_loop_smoke"
    ;;
  eval-included)
    python3 "$RUNNER" eval-included --out-dir "$ROOT/tmp/fog_chess_loop_included"
    ;;
  compare)
    args=(python3 "$RUNNER" compare --out-dir "$ROOT/tmp/fog_chess_loop_compare")
    if [[ -n "${STOCKFISH_PATH:-}" ]]; then
      args+=(--stockfish "$STOCKFISH_PATH")
    fi
    if [[ -n "${STOCKFISH_FOG_AGENT:-}" ]]; then
      args+=(--stockfish-fog-agent "$STOCKFISH_FOG_AGENT")
    fi
    if [[ -n "${HTML_FOG_AGENT:-}" ]]; then
      args+=(--html-fog-agent "$HTML_FOG_AGENT")
    fi
    if [[ -n "${FOG_CHESS_GENERATED_SEED:-}" ]]; then
      args+=(--generated-seed "$FOG_CHESS_GENERATED_SEED")
      args+=(--generated-scale "${FOG_CHESS_GENERATED_SCALE:-3}")
    fi
    "${args[@]}"
    ;;
  stress)
    if [[ -z "${FOG_CHESS_STRESS_AGENT:-}" || -z "${STOCKFISH_PATH:-}" ]]; then
      echo "stress requires FOG_CHESS_STRESS_AGENT and STOCKFISH_PATH" >&2
      exit 2
    fi
    args=(
      python3 "$RUNNER" stress
      --out-dir "$ROOT/tmp/fog_chess_loop_full_info_stockfish_stress"
      --fog-agent "$FOG_CHESS_STRESS_AGENT"
      --stockfish "$STOCKFISH_PATH"
      --movetime-ms "${FOG_CHESS_STOCKFISH_MOVETIME_MS:-20}"
      --max-plies "${FOG_CHESS_STRESS_MAX_PLIES:-40}"
    )
    if [[ -n "${FOG_CHESS_GENERATED_SEED:-}" ]]; then
      args+=(--generated-seed "$FOG_CHESS_GENERATED_SEED")
      args+=(--generated-scale "${FOG_CHESS_GENERATED_SCALE:-3}")
    fi
    "${args[@]}"
    ;;
  *)
    echo "usage: $0 [smoke|eval-included|compare|stress]" >&2
    exit 2
    ;;
esac

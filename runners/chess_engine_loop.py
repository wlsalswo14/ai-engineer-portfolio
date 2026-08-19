#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine


ROOT = Path(__file__).resolve().parents[2]
LOCAL_STOCKFISH = ROOT / "tmp" / "stockfish_local" / "root" / "usr" / "games" / "stockfish"
REFERENCE_ELO = 1320


SUITES: dict[str, list[str]] = {
    "mini_opening": [
        chess.STARTING_FEN,
        "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
    ],
    "opening_gauntlet": [
        chess.STARTING_FEN,
        "rnbqkbnr/pppp1ppp/4p3/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 2",
        "rnbqkbnr/ppp2ppp/4p3/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq c3 0 2",
        "r1bqkbnr/pppppppp/2n5/8/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 2",
    ],
    "advantage_conversion": [
        "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPQPPP/RNB1KBNR w KQkq - 0 1",
        "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "8/8/8/8/8/8/4K3/4Q2k w - - 0 1",
    ],
}


CHESS_ENGINE_TASK_PROMPT = """\
# Task: build a chess engine from scratch

Create a Python file named `engine.py`.

The engine must speak enough UCI over stdin/stdout to play games:

```text
uci                  -> print id/name lines, then uciok
isready              -> print readyok
ucinewgame           -> reset internal state
position startpos [moves ...]
position fen <six-field-fen> [moves ...]
go movetime <ms>     -> print exactly one legal `bestmove <uci_move>`
quit                 -> exit
```

The evaluator will play the engine against Stockfish at a tiny per-move budget.
Stockfish is only the opponent/evaluator. Do not inspect, cite, copy, or adapt
from Stockfish, commercial chess engines, python-chess, Sunfish, TSCP, or any
other chess engine/library source. Implement move generation, position state,
search, and evaluation yourself using only the Python standard library.

Your engine should prioritize:

- always returning legal moves before the timeout,
- not hanging on malformed or unfamiliar positions,
- basic material/king-safety/pawn/piece evaluation,
- at least shallow minimax/alpha-beta or a similarly concrete search,
- fast move ordering so `go movetime 20` still responds.

Leave only `engine.py` as the final engine artifact.
"""


def resolve_stockfish_path() -> Path:
    explicit = os.environ.get("STOCKFISH_PATH")
    candidates = [Path(explicit)] if explicit else []
    found = shutil.which("stockfish")
    if found:
        candidates.append(Path(found))
    candidates.append(LOCAL_STOCKFISH)
    for path in candidates:
        if path and path.exists() and path.is_file():
            return path
    raise FileNotFoundError("Stockfish binary not found; set STOCKFISH_PATH or extract it under tmp/stockfish_local")


def estimate_elo_from_wdl(wins: int, draws: int, losses: int, reference_elo: int = REFERENCE_ELO) -> dict[str, Any]:
    games = wins + draws + losses
    if games <= 0:
        return {"games": 0, "score_rate": 0.0, "elo_diff": -800, "elo": reference_elo - 800, "reference_elo": reference_elo}
    score = wins + 0.5 * draws
    smoothed = (score + 0.5) / (games + 1.0)
    smoothed = min(0.999, max(0.001, smoothed))
    elo_diff = int(round(400 * math.log10(smoothed / (1.0 - smoothed))))
    return {
        "games": games,
        "score_rate": round(score / games, 4),
        "smoothed_score_rate": round(smoothed, 4),
        "elo_diff": elo_diff,
        "elo": reference_elo + elo_diff,
        "reference_elo": reference_elo,
    }


def static_candidate_check(engine_path: Path) -> dict[str, Any]:
    text = engine_path.read_text(encoding="utf-8", errors="replace") if engine_path.exists() else ""
    lowered = text.lower()
    violations: list[str] = []
    internal_test_engine = "bench_internal_test_engine" in lowered
    if not engine_path.exists():
        violations.append("missing_engine")
    if "stockfish" in lowered:
        violations.append("mentions_stockfish")
    if re.search(r"^\s*(import|from)\s+chess\b", text, re.M) and not internal_test_engine:
        violations.append("imports_chess_library")
    if "python-chess" in lowered or "python_chess" in lowered:
        violations.append("mentions_python_chess")
    for marker in ["sunfish", "tscp", "fairy-stockfish", "komodo", "houdini", "lc0", "leela"]:
        if marker in lowered:
            violations.append(f"mentions_{marker.replace('-', '_')}")
    return {"ok": not violations, "violations": sorted(set(violations)), "bytes": len(text)}


def build_codex_command(work_dir: Path, model: str, effort: str, output_last_message: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "-",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-C",
        str(work_dir.resolve()),
        "--sandbox",
        "workspace-write",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        'service_tier="fast"',
        "--output-last-message",
        str(output_last_message.resolve()),
        "--json",
    ]


def run_process_group_with_timeout(
    cmd: list[str],
    cwd: Path,
    stdin_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str],
    timeout_sec: float,
) -> dict[str, Any]:
    start = time.time()
    with stdin_path.open("rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
            start_new_session=True,
        )
        try:
            returncode = proc.wait(timeout=timeout_sec)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=2)
            returncode = 124
    return {"returncode": returncode, "timed_out": timed_out, "wall_clock_sec": round(time.time() - start, 3)}


class UciProcess:
    def __init__(self, engine_path: Path, timeout_sec: float = 4.0):
        self.engine_path = engine_path
        self.timeout_sec = timeout_sec
        self.proc: subprocess.Popen[str] | None = None

    def __enter__(self) -> "UciProcess":
        self.proc = subprocess.Popen(
            [sys.executable, str(self.engine_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.send("uci")
        self.wait_for("uciok")
        self.send("isready")
        self.wait_for("readyok")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=1)
            except Exception:
                self.proc.kill()

    def send(self, line: str) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def wait_for(self, marker: str) -> str:
        assert self.proc is not None and self.proc.stdout is not None
        deadline = time.time() + self.timeout_sec
        lines: list[str] = []
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if line == "" and self.proc.poll() is not None:
                raise RuntimeError(f"engine exited before {marker}: {lines[-5:]}")
            line = line.strip()
            if line:
                lines.append(line)
            if line == marker or line.startswith(marker + " "):
                return line
        raise TimeoutError(f"timed out waiting for {marker}: {lines[-5:]}")

    def bestmove(self, board: chess.Board, movetime_ms: int) -> chess.Move:
        self.send("position fen " + board.fen())
        self.send(f"go movetime {movetime_ms}")
        line = self.wait_for("bestmove")
        parts = line.split()
        if len(parts) < 2 or parts[1] == "(none)":
            raise ValueError(f"bad bestmove line: {line}")
        move = chess.Move.from_uci(parts[1])
        if move not in board.legal_moves:
            raise ValueError(f"illegal move {move.uci()} in {board.fen()}")
        return move


def material_score(board: chess.Board) -> int:
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
    }
    total = 0
    for piece_type, value in values.items():
        total += len(board.pieces(piece_type, chess.WHITE)) * value
        total -= len(board.pieces(piece_type, chess.BLACK)) * value
    return total


def adjudicate(board: chess.Board, candidate_color: chess.Color) -> float:
    if board.is_checkmate():
        winner = not board.turn
        return 1.0 if winner == candidate_color else 0.0
    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
        return 0.5
    score = material_score(board)
    if candidate_color == chess.BLACK:
        score = -score
    if score >= 150:
        return 1.0
    if score <= -150:
        return 0.0
    return 0.5


def play_one_game(
    candidate: UciProcess,
    stockfish: chess.engine.SimpleEngine,
    fen: str,
    candidate_color: chess.Color,
    movetime_ms: int,
    max_plies: int,
    stockfish_depth: int,
) -> dict[str, Any]:
    board = chess.Board(fen)
    moves: list[str] = []
    illegal_loss = False
    error = None
    for _ in range(max_plies):
        if board.is_game_over(claim_draw=True):
            break
        try:
            if board.turn == candidate_color:
                move = candidate.bestmove(board, movetime_ms)
            else:
                result = stockfish.play(board, chess.engine.Limit(depth=stockfish_depth, time=movetime_ms / 1000.0))
                move = result.move
                if move not in board.legal_moves:
                    raise ValueError(f"stockfish illegal move {move}")
        except Exception as exc:  # candidate timeout/crash/illegal means loss
            illegal_loss = board.turn == candidate_color
            error = str(exc)
            break
        board.push(move)
        moves.append(move.uci())
    candidate_score = 0.0 if illegal_loss else adjudicate(board, candidate_color)
    return {
        "fen": fen,
        "candidate_color": "white" if candidate_color == chess.WHITE else "black",
        "score": candidate_score,
        "result": "win" if candidate_score == 1.0 else "draw" if candidate_score == 0.5 else "loss",
        "illegal_loss": illegal_loss,
        "error": error,
        "plies": len(moves),
        "final_fen": board.fen(),
        "moves": moves,
    }


def summarize_games(games: list[dict[str, Any]], reference_elo: int) -> dict[str, Any]:
    wins = sum(1 for game in games if game["score"] == 1.0)
    draws = sum(1 for game in games if game["score"] == 0.5)
    losses = sum(1 for game in games if game["score"] == 0.0)
    return {
        "games": len(games),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "illegal_losses": sum(1 for game in games if game.get("illegal_loss")),
        "elo": estimate_elo_from_wdl(wins, draws, losses, reference_elo),
    }


def evaluate_engine(
    engine_path: Path,
    suites: list[str],
    games_per_fen: int,
    movetime_ms: int,
    max_plies: int,
    stockfish_elo: int,
    stockfish_depth: int,
    timeout_sec: float,
) -> dict[str, Any]:
    static = static_candidate_check(engine_path)
    if not static["ok"]:
        return {"static": static, "overall": {"games": 0, "wins": 0, "draws": 0, "losses": 0, "illegal_losses": 0, "elo": estimate_elo_from_wdl(0, 0, 0, stockfish_elo)}, "suites": {}}

    stockfish_path = resolve_stockfish_path()
    suite_results: dict[str, Any] = {}
    all_games: list[dict[str, Any]] = []
    with UciProcess(engine_path, timeout_sec=timeout_sec) as candidate:
        with chess.engine.SimpleEngine.popen_uci(str(stockfish_path)) as stockfish:
            try:
                stockfish.configure({"UCI_LimitStrength": True, "UCI_Elo": stockfish_elo})
            except Exception:
                try:
                    stockfish.configure({"Skill Level": 0})
                except Exception:
                    pass
            for suite in suites:
                games: list[dict[str, Any]] = []
                for fen in SUITES[suite]:
                    for repeat in range(games_per_fen):
                        colors = [chess.WHITE, chess.BLACK] if repeat % 2 == 0 else [chess.BLACK, chess.WHITE]
                        for color in colors:
                            games.append(play_one_game(candidate, stockfish, fen, color, movetime_ms, max_plies, stockfish_depth))
                suite_results[suite] = summarize_games(games, stockfish_elo)
                suite_results[suite]["sample_games"] = games[:4]
                all_games.extend(games)
    return {"static": static, "overall": summarize_games(all_games, stockfish_elo), "suites": suite_results}


def write_random_uci_test_engine(path: Path) -> None:
    path.write_text(
        r'''
# BENCH_INTERNAL_TEST_ENGINE: dependency shortcut used only to smoke-test the harness.
import random
import sys

chess = __import__("ch" + "ess")
board = chess.Board()

def set_position(line):
    global board
    parts = line.strip().split()
    if len(parts) >= 2 and parts[1] == "startpos":
        board = chess.Board()
        if "moves" in parts:
            for mv in parts[parts.index("moves") + 1:]:
                try:
                    board.push(chess.Move.from_uci(mv))
                except Exception:
                    break
    elif len(parts) >= 8 and parts[1] == "fen":
        fen_parts = []
        for token in parts[2:]:
            if token == "moves":
                break
            fen_parts.append(token)
            if len(fen_parts) == 6:
                break
        board = chess.Board(" ".join(fen_parts))
        if "moves" in parts:
            for mv in parts[parts.index("moves") + 1:]:
                try:
                    board.push(chess.Move.from_uci(mv))
                except Exception:
                    break

for raw in sys.stdin:
    line = raw.strip()
    if line == "uci":
        print("id name bench-random", flush=True)
        print("uciok", flush=True)
    elif line == "isready":
        print("readyok", flush=True)
    elif line == "ucinewgame":
        board = chess.Board()
    elif line.startswith("position "):
        try:
            set_position(line)
        except Exception:
            board = chess.Board()
    elif line.startswith("go "):
        moves = list(board.legal_moves)
        print("bestmove " + (random.choice(moves).uci() if moves else "0000"), flush=True)
    elif line == "quit":
        break
'''.lstrip(),
        encoding="utf-8",
    )


def public_feedback_from_eval(eval_result: dict[str, Any]) -> str:
    overall = eval_result.get("overall", {})
    elo = overall.get("elo", {})
    return textwrap.dedent(
        f"""\
        Public feedback from the last engine:
        - games: {overall.get('games', 0)}
        - W/D/L: {overall.get('wins', 0)}/{overall.get('draws', 0)}/{overall.get('losses', 0)}
        - illegal_losses: {overall.get('illegal_losses', 0)}
        - estimated_elo_vs_reference: {elo.get('elo')}
        - score_rate: {elo.get('score_rate')}

        Improve legal move reliability first, then search/evaluation strength.
        """
    )


def mode_includes_previous_engine(mode: str) -> bool:
    return mode in {"cumulative_hidden_eval_loop", "solver_visible_public_eval"}


def write_public_eval(work_dir: Path, stockfish_path: Path) -> None:
    script = f"""\
#!/usr/bin/env python3
import json
import os
import subprocess
import sys

cmd = [
    sys.executable,
    {str((ROOT / 'scripts' / 'chess_engine_bench.py').resolve())!r},
    "evaluate-engine",
    "--engine", "engine.py",
    "--suites", "mini_opening",
    "--games-per-fen", "1",
    "--movetime-ms", "20",
    "--max-plies", "24",
    "--stockfish-depth", "1",
    "--stockfish-elo", "1320",
]
env = dict(os.environ)
env["STOCKFISH_PATH"] = {str(stockfish_path.resolve())!r}
proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=30)
print(proc.stdout)
if proc.stderr:
    print(proc.stderr, file=sys.stderr)
raise SystemExit(proc.returncode)
"""
    path = work_dir / "public_eval.py"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def run_codex_round(
    round_dir: Path,
    model: str,
    effort: str,
    mode: str,
    feedback: str | None,
    previous_engine: str | None,
    timeout_sec: int,
) -> dict[str, Any]:
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "TASK.md").write_text(CHESS_ENGINE_TASK_PROMPT, encoding="utf-8")
    if previous_engine:
        (round_dir / "previous_engine.py").write_text(previous_engine, encoding="utf-8")
    if feedback:
        (round_dir / "feedback.md").write_text(feedback, encoding="utf-8")
    if mode == "solver_visible_public_eval":
        write_public_eval(round_dir, resolve_stockfish_path())

    prompt = (
        "Read TASK.md and create engine.py in the current directory. "
        "Use only the current directory. Do not inspect parent directories. "
        "Do not use chess libraries or engine source. "
        "Do not create memory directories, task trackers, design docs, reports, or extra project scaffolding; this isolated benchmark only wants engine.py. "
    )
    if feedback:
        prompt += "Use feedback.md to improve the previous result. "
    if previous_engine:
        prompt += "You may reuse or rewrite previous_engine.py, but the final artifact must be engine.py. "
    if mode == "solver_visible_public_eval":
        prompt += "You may run python3 public_eval.py for public smoke feedback, but hidden evaluation is separate. "
    prompt += "When finished, leave engine.py on disk.\n"
    (round_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    events = round_dir / "events.jsonl"
    stderr = round_dir / "stderr.txt"
    last = round_dir / "last_message.txt"
    cmd = build_codex_command(round_dir, model, effort, last)
    env = dict(os.environ)
    env.setdefault("CODEX_HOME", str(Path.home() / ".codex-1"))
    result = run_process_group_with_timeout(
        cmd,
        cwd=round_dir,
        stdin_path=round_dir / "prompt.txt",
        stdout_path=events,
        stderr_path=stderr,
        env=env,
        timeout_sec=timeout_sec,
    )
    result["engine"] = str(round_dir / "engine.py")
    return result


def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for model in args.models:
        for mode in args.modes:
            for trial in range(1, args.trials + 1):
                feedback = None
                previous_engine = None
                history: list[dict[str, Any]] = []
                rounds = 1 if mode == "one_shot" else args.rounds
                for round_index in range(1, rounds + 1):
                    safe_model = model.replace("/", "_")
                    round_dir = out_dir / safe_model / mode / f"trial_{trial:02d}" / f"round_{round_index:02d}"
                    prompt_previous = previous_engine if mode_includes_previous_engine(mode) else None
                    run = run_codex_round(round_dir, model, args.effort, mode, feedback, prompt_previous, args.timeout_sec)
                    engine_path = Path(run["engine"])
                    if engine_path.exists():
                        eval_result = evaluate_engine(
                            engine_path,
                            args.suites,
                            args.games_per_fen,
                            args.movetime_ms,
                            args.max_plies,
                            args.stockfish_elo,
                            args.stockfish_depth,
                            args.engine_timeout_sec,
                        )
                        previous_engine = engine_path.read_text(encoding="utf-8", errors="replace")
                    else:
                        eval_result = {
                            "static": {"ok": False, "violations": ["missing_engine"], "bytes": 0},
                            "overall": summarize_games([], args.stockfish_elo),
                            "suites": {},
                        }
                    feedback = public_feedback_from_eval(eval_result)
                    row = {
                        "model": model,
                        "effort": args.effort,
                        "mode": mode,
                        "trial": trial,
                        "round": round_index,
                        "run": run,
                        "eval": eval_result,
                        "round_dir": str(round_dir),
                    }
                    history.append(row)
                    rows.append(row)
                    (round_dir / "eval_result.json").write_text(json.dumps(eval_result, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps(compact_row(row), ensure_ascii=False), flush=True)
                trial_dir = out_dir / safe_model / mode / f"trial_{trial:02d}"
                (trial_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"rows": rows, "summary": summarize_matrix(rows)}
    (out_dir / "chess_benchmark_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    overall = row["eval"]["overall"]
    return {
        "model": row["model"],
        "mode": row["mode"],
        "trial": row["trial"],
        "round": row["round"],
        "timed_out": row["run"]["timed_out"],
        "returncode": row["run"]["returncode"],
        "games": overall["games"],
        "wdl": [overall["wins"], overall["draws"], overall["losses"]],
        "illegal_losses": overall["illegal_losses"],
        "elo": overall["elo"]["elo"],
        "score_rate": overall["elo"]["score_rate"],
        "static_ok": row["eval"]["static"]["ok"],
    }


def summarize_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["model"], row["mode"]), []).append(row)
    summary: list[dict[str, Any]] = []
    for (model, mode), group in sorted(groups.items()):
        best_by_trial: dict[int, dict[str, Any]] = {}
        for row in group:
            current = best_by_trial.get(row["trial"])
            if current is None or row["eval"]["overall"]["elo"]["elo"] > current["eval"]["overall"]["elo"]["elo"]:
                best_by_trial[row["trial"]] = row
        best_elos = [row["eval"]["overall"]["elo"]["elo"] for row in best_by_trial.values()]
        all_elos = [row["eval"]["overall"]["elo"]["elo"] for row in group]
        summary.append(
            {
                "model": model,
                "mode": mode,
                "round_rows": len(group),
                "trials": len(best_by_trial),
                "all_elos": all_elos,
                "best_elos": best_elos,
                "mean_best_elo": round(sum(best_elos) / len(best_elos), 2) if best_elos else None,
                "max_best_elo": max(best_elos) if best_elos else None,
                "static_failures": sum(1 for row in group if not row["eval"]["static"]["ok"]),
            }
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("write-task")
    p.add_argument("--out-dir", required=True)

    p = sub.add_parser("write-random-engine")
    p.add_argument("--out", required=True)

    p = sub.add_parser("evaluate-engine")
    p.add_argument("--engine", required=True)
    p.add_argument("--suites", nargs="+", choices=sorted(SUITES), default=["opening_gauntlet", "advantage_conversion"])
    p.add_argument("--games-per-fen", type=int, default=1)
    p.add_argument("--movetime-ms", type=int, default=50)
    p.add_argument("--max-plies", type=int, default=80)
    p.add_argument("--stockfish-elo", type=int, default=REFERENCE_ELO)
    p.add_argument("--stockfish-depth", type=int, default=1)
    p.add_argument("--timeout-sec", type=float, default=4.0)

    p = sub.add_parser("run-matrix")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--modes", nargs="+", choices=["one_shot", "hidden_eval_loop", "cumulative_hidden_eval_loop", "solver_visible_public_eval"], required=True)
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--effort", default="low")
    p.add_argument("--timeout-sec", type=int, default=420)
    p.add_argument("--engine-timeout-sec", type=float, default=4.0)
    p.add_argument("--suites", nargs="+", choices=sorted(SUITES), default=["opening_gauntlet", "advantage_conversion"])
    p.add_argument("--games-per-fen", type=int, default=1)
    p.add_argument("--movetime-ms", type=int, default=50)
    p.add_argument("--max-plies", type=int, default=80)
    p.add_argument("--stockfish-elo", type=int, default=REFERENCE_ELO)
    p.add_argument("--stockfish-depth", type=int, default=1)

    args = parser.parse_args(argv)
    if args.cmd == "write-task":
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "TASK.md"
        path.write_text(CHESS_ENGINE_TASK_PROMPT, encoding="utf-8")
        print(path)
        return 0
    if args.cmd == "write-random-engine":
        write_random_uci_test_engine(Path(args.out))
        print(args.out)
        return 0
    if args.cmd == "evaluate-engine":
        result = evaluate_engine(Path(args.engine), args.suites, args.games_per_fen, args.movetime_ms, args.max_plies, args.stockfish_elo, args.stockfish_depth, args.timeout_sec)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["static"]["ok"] else 2
    if args.cmd == "run-matrix":
        report = run_matrix(args)
        print(json.dumps({"summary": report["summary"]}, ensure_ascii=False, indent=2))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())

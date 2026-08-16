from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from loop_evolution.platform.common import content_hash
from loop_evolution.platform.domain import TaskCase
from loop_evolution.platform.runtime.answers import extract_final_answer


class ChessBenchContractError(RuntimeError):
    """The frozen evaluator contract is unavailable or has changed."""


class ChessBenchCandidateError(ValueError):
    """The submitted engine does not satisfy the public candidate contract."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*.py") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class WindowsUciProcess:
    """Small Windows UCI boundary for an isolated, statically restricted Python engine."""

    def __init__(
        self,
        engine_path: Path,
        *,
        initial_handshake_ms: int,
        new_game_ready_ms: int,
        move_grace_ms: int,
        total_handshake_wall_ms: int,
    ) -> None:
        self.engine_path = engine_path
        self.initial_handshake_ms = initial_handshake_ms
        self.new_game_ready_ms = new_game_ready_ms
        self.move_grace_ms = move_grace_ms
        self.total_handshake_wall_ms = total_handshake_wall_ms
        self.proc: subprocess.Popen[str] | None = None
        self.lines: queue.Queue[str] = queue.Queue(maxsize=128)
        self.reader: threading.Thread | None = None
        self.protocol_failure: str | None = None
        self.handshake_wall_seconds = 0.0

    def __enter__(self) -> WindowsUciProcess:
        environment = {
            "PATH": str(Path(sys.executable).parent),
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "TEMP": tempfile.gettempdir(),
            "TMP": tempfile.gettempdir(),
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-S", "-u", str(self.engine_path)],
            cwd=self.engine_path.parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader.start()
        try:
            started = time.monotonic()
            self.send("uci")
            self.wait_for("uciok", self.initial_handshake_ms / 1000.0)
            self.send("isready")
            self.wait_for("readyok", self.initial_handshake_ms / 1000.0)
            self.handshake_wall_seconds += time.monotonic() - started
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        if self.proc is None:
            return
        if self.proc.poll() is None:
            with suppress(Exception):
                self.send("quit")
                self.proc.wait(timeout=0.5)
        if self.proc.poll() is None:
            with suppress(Exception):
                self.proc.kill()
                self.proc.wait(timeout=1)
        if self.proc.stdin:
            self.proc.stdin.close()
        if self.proc.stdout:
            self.proc.stdout.close()

    def _read_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline(16_385)
            if not line:
                return
            if len(line) > 16_384 or not line.endswith("\n"):
                self.protocol_failure = "uci_output_line_limit"
                return
            try:
                self.lines.put_nowait(line)
            except queue.Full:
                self.protocol_failure = "uci_pending_output_limit"
                return

    def send(self, line: str) -> None:
        if self.proc is None or self.proc.stdin is None or self.proc.poll() is not None:
            raise RuntimeError("candidate engine is not running")
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def wait_for(self, marker: str, timeout_seconds: float) -> str:
        assert self.proc is not None
        deadline = time.monotonic() + timeout_seconds
        while True:
            if self.protocol_failure:
                raise RuntimeError(self.protocol_failure)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {marker}")
            try:
                line = self.lines.get(timeout=min(remaining, 0.025)).strip()
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise RuntimeError("candidate engine exited") from None
                continue
            if line == marker or line.startswith(marker + " "):
                return line

    def _drain(self) -> None:
        while True:
            try:
                self.lines.get_nowait()
            except queue.Empty:
                return

    def new_game(self) -> None:
        started = time.monotonic()
        self._drain()
        self.send("ucinewgame")
        self.send("isready")
        self.wait_for("readyok", self.new_game_ready_ms / 1000.0)
        self.handshake_wall_seconds += time.monotonic() - started
        if self.handshake_wall_seconds * 1000 > self.total_handshake_wall_ms:
            raise RuntimeError("candidate exceeded total UCI handshake wall cap")

    def bestmove(self, board: Any, movetime_ms: int) -> Any:
        import chess

        self._drain()
        self.send("position fen " + board.fen())
        self.send(f"go movetime {movetime_ms}")
        line = self.wait_for(
            "bestmove",
            (movetime_ms + self.move_grace_ms) / 1000.0,
        )
        parts = line.split()
        if len(parts) < 2 or parts[1] == "(none)":
            raise ValueError(f"invalid bestmove response: {line}")
        move = chess.Move.from_uci(parts[1])
        if move not in board.legal_moves:
            raise ValueError(f"illegal move: {move.uci()}")
        return move


@dataclass(frozen=True)
class ChessBench100Scorer:
    """Score a complete-file UCI engine on the frozen 50-opening/100-game contract."""

    adapter_version: str = "loopsy-standard-chess-windows-adapter-v1"
    must_beat_score_rate: float | None = None
    result_cache_dir: Path | None = None

    _ALLOWED_IMPORTS = frozenset(
        {
            "array",
            "bisect",
            "collections",
            "dataclasses",
            "enum",
            "functools",
            "heapq",
            "itertools",
            "math",
            "operator",
            "random",
            "sys",
            "time",
            "typing",
        }
    )
    _ENGINE_MARKERS = (
        "stockfish",
        "python-chess",
        "python_chess",
        "sunfish",
        "tscp",
        "fairy-stockfish",
        "komodo",
        "houdini",
        "lc0",
        "leela",
    )

    @staticmethod
    def _maximum_possible_score_rate(
        *, wins: int, draws: int, games_played: int, scheduled_games: int
    ) -> float:
        if not 0 <= games_played <= scheduled_games or scheduled_games <= 0:
            raise ValueError("invalid early-stop game counts")
        points = float(wins) + 0.5 * float(draws)
        return (points + float(scheduled_games - games_played)) / float(
            scheduled_games
        )

    def verify_public(
        self,
        output: str,
    ) -> tuple[float, str | None, tuple[str, ...]]:
        try:
            source = self._parse_engine(output)
            self._static_check(source)
        except (ChessBenchCandidateError, json.JSONDecodeError, SyntaxError, TypeError):
            return 0.0, "invalid_engine_payload", ()
        engine_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        try:
            self._public_uci_smoke(source)
        except Exception:
            return 0.0, "public_uci_smoke_failed", (f"engine-source:{engine_hash}",)
        return 1.0, None, (f"engine-source:{engine_hash}", "public-uci-smoke:passed")

    def score(
        self,
        case: TaskCase,
        output: str,
    ) -> tuple[float, str | None, tuple[str, ...]]:
        try:
            source = self._parse_engine(output)
            self._static_check(source)
            contract, runner, chess_module = self._contract(case)
        except (
            ChessBenchCandidateError,
            ChessBenchContractError,
            json.JSONDecodeError,
            SyntaxError,
            TypeError,
            ValueError,
        ) as exc:
            kind = "evaluator_contract_error" if isinstance(exc, ChessBenchContractError) else "invalid_engine_payload"
            return 0.0, kind, ()

        engine_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        contract_hash = content_hash(contract)
        result_root = (
            self.result_cache_dir.resolve()
            if self.result_cache_dir is not None
            else Path(str(case.metadata["result_dir"])).resolve()
        )
        full_result_path = result_root / f"{contract_hash[:16]}-{engine_hash[:16]}.json"
        if self.must_beat_score_rate is None:
            result_path = full_result_path
        else:
            cutoff_hash = content_hash(
                {
                    "rule": "mathematical_strict_score_upper_bound_after_complete_pairs_v1",
                    "must_beat_score_rate": self.must_beat_score_rate,
                }
            )[:16]
            result_path = result_root / (
                f"{contract_hash[:16]}-{engine_hash[:16]}-cutoff-{cutoff_hash}.json"
            )
        cached = self._cached_result(full_result_path, contract_hash, engine_hash)
        if cached is not None:
            result_path = full_result_path
        if cached is None and result_path != full_result_path:
            cached = self._cached_result(result_path, contract_hash, engine_hash)
        if cached is None:
            try:
                result = self._run_match(
                    source=source,
                    contract=contract,
                    runner=runner,
                    chess_module=chess_module,
                )
            except ChessBenchContractError:
                return 0.0, "evaluator_contract_error", ()
            payload = {
                "schema_version": 1,
                "adapter_version": self.adapter_version,
                "contract_sha256": contract_hash,
                "engine_sha256": engine_hash,
                "result": result,
            }
            payload["content_sha256"] = content_hash(payload)
            _atomic_json(result_path, payload)
        else:
            result = dict(cached["result"])

        summary = dict(result["summary"])
        if not summary.get("valid", False):
            if summary.get("promotion_eliminated", False):
                return (
                    0.0,
                    "promotion_mathematically_eliminated",
                    (
                        f"chessbench-result:{result_path}",
                        f"chessbench-contract:{contract_hash}",
                        f"engine-source:{engine_hash}",
                        (
                            "chessbench-early-stop:"
                            f"{summary.get('valid_games', 0)}-games:"
                            f"upper-{summary.get('maximum_possible_score_rate')}"
                        ),
                    ),
                )
            return (
                0.0,
                "evaluator_failure",
                (f"chessbench-result:{result_path}", f"engine-source:{engine_hash}"),
            )
        games = int(summary["valid_games"])
        score_rate = (float(summary["wins"]) + 0.5 * float(summary["draws"])) / games
        evidence = (
            f"chessbench-result:{result_path}",
            f"chessbench-contract:{contract_hash}",
            f"engine-source:{engine_hash}",
            (f"chessbench-wdl:{summary['wins']}-{summary['draws']}-{summary['losses']}"),
        )
        return score_rate, None, evidence

    @staticmethod
    def _parse_engine(output: str) -> str:
        payload = json.loads(extract_final_answer(output))
        if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
            raise ChessBenchCandidateError("answer must contain a files object")
        files = payload["files"]
        if set(files) != {"engine.py"} or not isinstance(files["engine.py"], str):
            raise ChessBenchCandidateError("answer must contain only engine.py")
        if not files["engine.py"].strip():
            raise ChessBenchCandidateError("engine.py is empty")
        return files["engine.py"]

    def _static_check(self, source: str) -> None:
        lowered = source.lower()
        violations = [marker for marker in self._ENGINE_MARKERS if marker in lowered]
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"__import__", "eval", "exec", "compile", "open"}:
                    violations.append(f"forbidden_call:{node.func.id}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [item.name.split(".", 1)[0] for item in node.names]
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module.split(".", 1)[0])
                violations.extend(f"forbidden_import:{name}" for name in names if name not in self._ALLOWED_IMPORTS)
        if violations:
            raise ChessBenchCandidateError(
                "engine violates the closed-book boundary: " + ",".join(sorted(set(violations)))
            )

    def _public_uci_smoke(self, source: str) -> None:
        import chess

        with tempfile.TemporaryDirectory(prefix="v3lite-chess-public-") as raw:
            engine_path = Path(raw) / "engine.py"
            engine_path.write_text(source, encoding="utf-8")
            with WindowsUciProcess(
                engine_path,
                initial_handshake_ms=5000,
                new_game_ready_ms=500,
                move_grace_ms=200,
                total_handshake_wall_ms=10_000,
            ) as candidate:
                candidate.new_game()
                candidate.bestmove(chess.Board(), 100)

    def _contract(
        self,
        case: TaskCase,
    ) -> tuple[dict[str, Any], ModuleType, ModuleType]:
        try:
            import chess
            import chess.engine
        except ImportError as exc:
            raise ChessBenchContractError("python-chess evaluator dependency is unavailable") from exc
        metadata = case.metadata
        runner_path = self._pinned_file(metadata, "runner_path", "runner_sha256")
        openings_path = self._pinned_file(metadata, "openings_path", "openings_sha256")
        stockfish_path = self._pinned_file(metadata, "stockfish_path", "stockfish_sha256")
        expected_version = str(metadata.get("python_chess_version", ""))
        if chess.__version__ != expected_version:
            raise ChessBenchContractError("python-chess version changed")
        expected_tree = str(metadata.get("python_chess_source_tree_sha256", ""))
        if _python_source_tree_sha256(Path(chess.__file__).resolve().parent) != expected_tree:
            raise ChessBenchContractError("python-chess source tree changed")
        runner = self._load_runner(runner_path)
        openings = runner.load_official_chess_openings(openings_path)
        if openings["sha256"] != str(metadata["openings_sha256"]):
            raise ChessBenchContractError("frozen opening bytes changed")
        tier_index = int(metadata["tier_index"])
        tier = runner.stockfish_node_ladder(tier_index + 1)[tier_index]
        contract = {
            "adapter_version": self.adapter_version,
            "runner_sha256": str(metadata["runner_sha256"]),
            "openings_sha256": str(metadata["openings_sha256"]),
            "stockfish_sha256": str(metadata["stockfish_sha256"]),
            "python_chess_version": expected_version,
            "python_chess_source_tree_sha256": expected_tree,
            "tier_index": tier_index,
            "stockfish_nodes": int(tier["nodes_per_move"]),
            "candidate_movetime_ms": int(metadata.get("candidate_movetime_ms", 100)),
            "candidate_response_grace_ms": int(metadata.get("candidate_response_grace_ms", 50)),
            "candidate_initial_handshake_timeout_ms": int(metadata.get("candidate_initial_handshake_timeout_ms", 5000)),
            "candidate_new_game_ready_timeout_ms": int(metadata.get("candidate_new_game_ready_timeout_ms", 250)),
            "candidate_total_handshake_wall_cap_ms": int(metadata.get("candidate_total_handshake_wall_cap_ms", 30_000)),
            "max_plies": int(metadata.get("max_plies", 600)),
            "scheduled_games": 100,
            "opening_count": 50,
            "runner_path": str(runner_path),
            "openings_path": str(openings_path),
            "stockfish_path": str(stockfish_path),
            "result_dir": str(Path(str(metadata["result_dir"])).resolve()),
        }
        return contract, runner, chess

    @staticmethod
    def _pinned_file(metadata: Any, path_key: str, hash_key: str) -> Path:
        path = Path(str(metadata.get(path_key, ""))).resolve()
        expected = str(metadata.get(hash_key, "")).lower()
        if not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ChessBenchContractError(f"missing frozen contract file: {path_key}")
        if _sha256_file(path) != expected:
            raise ChessBenchContractError(f"frozen contract hash mismatch: {path_key}")
        return path

    @staticmethod
    def _load_runner(path: Path) -> ModuleType:
        name = f"_v3lite_frozen_chessbench_{_sha256_file(path)[:16]}"
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ChessBenchContractError("cannot load frozen ChessBench runner")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(name, None)
            raise ChessBenchContractError("frozen ChessBench runner failed to load") from exc
        return module

    @staticmethod
    def _cached_result(
        path: Path,
        contract_hash: str,
        engine_hash: str,
    ) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expected = payload.pop("content_sha256")
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
        if (
            expected != content_hash(payload)
            or payload.get("contract_sha256") != contract_hash
            or payload.get("engine_sha256") != engine_hash
        ):
            return None
        return payload

    def _run_match(
        self,
        *,
        source: str,
        contract: dict[str, Any],
        runner: ModuleType,
        chess_module: ModuleType,
    ) -> dict[str, Any]:
        openings = runner.load_official_chess_openings(Path(contract["openings_path"]))
        schedule = runner.official_chess_game_schedule(openings["openings"])
        games: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="v3lite-chess-hidden-") as raw:
            engine_path = Path(raw) / "engine.py"
            engine_path.write_text(source, encoding="utf-8")
            try:
                candidate_context = WindowsUciProcess(
                    engine_path,
                    initial_handshake_ms=contract["candidate_initial_handshake_timeout_ms"],
                    new_game_ready_ms=contract["candidate_new_game_ready_timeout_ms"],
                    move_grace_ms=contract["candidate_response_grace_ms"],
                    total_handshake_wall_ms=contract["candidate_total_handshake_wall_cap_ms"],
                )
                candidate = candidate_context.__enter__()
            except Exception as exc:
                for item in schedule:
                    games.append(
                        runner._scheduled_failure_game(
                            item,
                            stockfish_nodes=contract["stockfish_nodes"],
                            failure_kind="candidate",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
            else:
                try:
                    try:
                        stockfish = chess_module.engine.SimpleEngine.popen_uci(
                            contract["stockfish_path"],
                            timeout=10,
                        )
                        stockfish.configure({"Threads": 1, "Hash": 16})
                    except Exception as exc:
                        raise ChessBenchContractError(f"Stockfish evaluator failed to start: {exc}") from exc
                    try:
                        for index, item in enumerate(schedule):
                            games.append(
                                runner.play_one_official_chess_game(
                                    candidate,
                                    stockfish,
                                    fen=item["fen"],
                                    opening_id=item["opening_id"],
                                    candidate_color=item["candidate_color"],
                                    candidate_movetime_ms=contract["candidate_movetime_ms"],
                                    stockfish_nodes=contract["stockfish_nodes"],
                                    max_plies=contract["max_plies"],
                                    game_token=f"v3lite-{index}",
                                )
                            )
                            if (
                                self.must_beat_score_rate is not None
                                and len(games) % 2 == 0
                            ):
                                partial = runner.summarize_official_chess_games(
                                    games
                                )
                                maximum_possible_score_rate = (
                                    self._maximum_possible_score_rate(
                                        wins=int(partial["wins"]),
                                        draws=int(partial["draws"]),
                                        games_played=len(games),
                                        scheduled_games=len(schedule),
                                    )
                                )
                                if maximum_possible_score_rate <= float(
                                    self.must_beat_score_rate
                                ):
                                    break
                    finally:
                        with suppress(Exception):
                            stockfish.quit()
                finally:
                    candidate_context.__exit__(None, None, None)
        summary = runner.summarize_official_chess_games(games)
        if len(games) < len(schedule):
            points = float(summary["wins"]) + 0.5 * float(summary["draws"])
            remaining = len(schedule) - len(games)
            maximum_possible_score_rate = self._maximum_possible_score_rate(
                wins=int(summary["wins"]),
                draws=int(summary["draws"]),
                games_played=len(games),
                scheduled_games=len(schedule),
            )
            summary.update(
                {
                    "valid": False,
                    "early_stopped": True,
                    "promotion_eliminated": True,
                    "must_beat_score_rate": self.must_beat_score_rate,
                    "points_earned": points,
                    "remaining_games_not_played": remaining,
                    "maximum_possible_score_rate": maximum_possible_score_rate,
                    "early_stop_rule": (
                        "stop after a complete color-swapped pair iff winning every remaining game "
                        "cannot strictly exceed must_beat_score_rate"
                    ),
                }
            )
        else:
            summary.update(
                {
                    "early_stopped": False,
                    "promotion_eliminated": False,
                    "must_beat_score_rate": self.must_beat_score_rate,
                }
            )
        return {
            "contract": contract,
            "summary": summary,
            "games": games,
        }

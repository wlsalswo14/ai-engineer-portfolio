#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_OUTPUT_CHARS = 4096
FILES = "abcdefgh"
WHITE = "PNBRQK"
BLACK = "pnbrqk"
PIECE_VALUES = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 100}
FORBIDDEN_CANDIDATE_TOKENS = [
    "subprocess",
    "socket",
    "urllib",
    "requests",
    "pathlib",
    "open(",
    "__file__",
    "os.",
    "benchmarks/data",
    "fog-chess-loop",
    "stockfish",
    "canonical_board",
    "full_board",
    "private_marker",
    "canary",
]
FORBIDDEN_OBSERVATION_FIELDS = {"legal_moves"}
PUBLIC_LEAK_TOKENS = [
    "canonical_board",
    "full_board",
    "legal_moves",
    "private_marker",
    "canary",
]


@dataclass(frozen=True)
class FogState:
    rows: tuple[str, ...]
    side_to_move: str = "white"
    turn: int = 0
    case_id: str = "custom"
    history: tuple[dict[str, Any], ...] = ()
    hidden_markers: tuple[str, ...] = ()

    @classmethod
    def from_rows(
        cls,
        rows: list[str] | tuple[str, ...],
        side_to_move: str = "white",
        case_id: str = "custom",
        history: tuple[dict[str, Any], ...] = (),
        hidden_markers: tuple[str, ...] = (),
    ) -> "FogState":
        if side_to_move not in {"white", "black"}:
            raise ValueError("side_to_move must be white or black")
        normalized = tuple(str(row) for row in rows)
        if len(normalized) != 8 or any(len(row) != 8 for row in normalized):
            raise ValueError("board must be 8 rows of 8 characters")
        allowed = set(".PNBRQKpnbrqk")
        if any(ch not in allowed for row in normalized for ch in row):
            raise ValueError("board contains unsupported pieces")
        return cls(
            rows=normalized,
            side_to_move=side_to_move,
            case_id=case_id,
            history=history,
            hidden_markers=hidden_markers,
        )

    @classmethod
    def start(cls) -> "FogState":
        return cls.from_rows(
            [
                "rnbqkbnr",
                "pppppppp",
                "........",
                "........",
                "........",
                "........",
                "PPPPPPPP",
                "RNBQKBNR",
            ],
            side_to_move="white",
            case_id="opening_white",
        )

    def observe(self, side: str) -> dict[str, Any]:
        if side not in {"white", "black"}:
            raise ValueError("side must be white or black")
        visible = self.visible_squares(side)
        visible_rows: list[str] = []
        for row in range(8):
            chars: list[str] = []
            for col in range(8):
                if (row, col) in visible:
                    piece = self.rows[row][col]
                    chars.append("." if piece == "." else piece)
                else:
                    chars.append("?")
            visible_rows.append("".join(chars))
        return {
            "case_id": self.case_id,
            "side": side,
            "side_to_move": self.side_to_move,
            "turn": self.turn,
            "visible_board": visible_rows,
            "fog_history": self.fog_history(side),
            "illegal_attempts": [],
            "move_format": "uci",
            "rules": {
                "self_check_allowed": True,
                "checkmate_disabled": True,
                "game_ends_by": "king_capture",
            },
        }

    def fog_history(self, side: str) -> list[str]:
        lines: list[str] = []
        for item in self.history:
            color = item.get("color")
            move = item.get("move", "???")
            if color == side:
                lines.append(str(move))
            else:
                lines.append("???")
        return lines

    def visible_squares(self, side: str) -> set[tuple[int, int]]:
        visible: set[tuple[int, int]] = set()
        for row in range(8):
            for col in range(8):
                piece = self.rows[row][col]
                if piece == "." or piece_side(piece) != side:
                    continue
                visible.add((row, col))
                for move in pseudo_legal_targets(self.rows, row, col):
                    visible.add(move)
        return visible


@dataclass(frozen=True)
class Fixture:
    name: str
    state: FogState
    side: str


def opponent_side(side: str) -> str:
    return "black" if side == "white" else "white"


def piece_side(piece: str) -> str | None:
    if piece in WHITE:
        return "white"
    if piece in BLACK:
        return "black"
    return None


def square_to_rc(square: str) -> tuple[int, int]:
    if len(square) != 2 or square[0] not in FILES or square[1] not in "12345678":
        raise ValueError(f"invalid square: {square}")
    return 8 - int(square[1]), FILES.index(square[0])


def rc_to_square(row: int, col: int) -> str:
    return f"{FILES[col]}{8 - row}"


def in_bounds(row: int, col: int) -> bool:
    return 0 <= row < 8 and 0 <= col < 8


def serialize_observation(observation: dict[str, Any]) -> str:
    return json.dumps(observation, sort_keys=True, separators=(",", ":"))


def pseudo_legal_targets(rows: tuple[str, ...], row: int, col: int) -> list[tuple[int, int]]:
    piece = rows[row][col]
    side = piece_side(piece)
    if side is None:
        return []
    lower = piece.lower()
    if lower == "p":
        return pawn_targets(rows, row, col, side)
    if lower == "n":
        return leaper_targets(rows, row, col, side, [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)])
    if lower == "k":
        return leaper_targets(rows, row, col, side, [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)])
    if lower == "b":
        return slider_targets(rows, row, col, side, [(-1, -1), (-1, 1), (1, -1), (1, 1)])
    if lower == "r":
        return slider_targets(rows, row, col, side, [(-1, 0), (1, 0), (0, -1), (0, 1)])
    if lower == "q":
        return slider_targets(
            rows,
            row,
            col,
            side,
            [(-1, -1), (-1, 1), (1, -1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)],
        )
    return []


def pawn_targets(rows: tuple[str, ...], row: int, col: int, side: str) -> list[tuple[int, int]]:
    direction = -1 if side == "white" else 1
    start_row = 6 if side == "white" else 1
    targets: list[tuple[int, int]] = []
    one = row + direction
    if in_bounds(one, col) and rows[one][col] == ".":
        targets.append((one, col))
        two = row + 2 * direction
        if row == start_row and in_bounds(two, col) and rows[two][col] == ".":
            targets.append((two, col))
    for dc in (-1, 1):
        nr, nc = row + direction, col + dc
        if not in_bounds(nr, nc):
            continue
        target_side = piece_side(rows[nr][nc])
        if target_side is not None and target_side != side:
            targets.append((nr, nc))
    return targets


def leaper_targets(
    rows: tuple[str, ...],
    row: int,
    col: int,
    side: str,
    deltas: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    targets: list[tuple[int, int]] = []
    for dr, dc in deltas:
        nr, nc = row + dr, col + dc
        if not in_bounds(nr, nc):
            continue
        target_side = piece_side(rows[nr][nc])
        if target_side != side:
            targets.append((nr, nc))
    return targets


def slider_targets(
    rows: tuple[str, ...],
    row: int,
    col: int,
    side: str,
    deltas: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    targets: list[tuple[int, int]] = []
    for dr, dc in deltas:
        nr, nc = row + dr, col + dc
        while in_bounds(nr, nc):
            target_side = piece_side(rows[nr][nc])
            if target_side == side:
                break
            targets.append((nr, nc))
            if target_side is not None:
                break
            nr += dr
            nc += dc
    return targets


def parse_uci(move: str) -> tuple[tuple[int, int], tuple[int, int], str | None]:
    text = move.strip().lower()
    if len(text) not in {4, 5}:
        raise ValueError("move must be UCI coordinate text")
    from_square = text[:2]
    to_square = text[2:4]
    promotion = text[4] if len(text) == 5 else None
    if promotion is not None and promotion not in "qrbn":
        raise ValueError("unsupported promotion")
    return square_to_rc(from_square), square_to_rc(to_square), promotion


def score_attempt(state: FogState, side: str, move: str) -> dict[str, Any]:
    try:
        (from_row, from_col), (to_row, to_col), promotion = parse_uci(move)
    except Exception:
        return {"score": 0.0, "reason": "illegal_format"}
    del promotion
    if side != state.side_to_move:
        return {"score": 0.0, "reason": "illegal_wrong_turn"}
    piece = state.rows[from_row][from_col]
    if piece == "." or piece_side(piece) != side:
        return {"score": 0.0, "reason": "illegal_source"}
    if (to_row, to_col) not in pseudo_legal_targets(state.rows, from_row, from_col):
        return {"score": 0.0, "reason": "illegal_move"}
    captured = state.rows[to_row][to_col]
    if captured.lower() == "k" and piece_side(captured) == opponent_side(side):
        return {"score": 1.0, "reason": "king_capture"}
    if captured != "." and piece_side(captured) == opponent_side(side):
        return {"score": 0.82, "reason": "visible_capture"}
    return {"score": 0.55, "reason": "legal_non_capture"}


def apply_pseudo_legal_move(state: FogState, side: str, move: str) -> tuple[FogState, dict[str, Any]]:
    scored = score_attempt(state, side, move)
    if scored["reason"].startswith("illegal"):
        return state, {"applied": False, **scored}
    (from_row, from_col), (to_row, to_col), promotion = parse_uci(move)
    rows = [list(row) for row in state.rows]
    piece = rows[from_row][from_col]
    captured = rows[to_row][to_col]
    rows[from_row][from_col] = "."
    if promotion is not None and piece.lower() == "p":
        piece = promotion.upper() if side == "white" else promotion.lower()
    rows[to_row][to_col] = piece
    next_rows = tuple("".join(row) for row in rows)
    history = state.history + (
        {
            "color": side,
            "move": move.strip().lower(),
            "capture": "" if captured == "." else captured,
        },
    )
    return (
        FogState(
            rows=next_rows,
            side_to_move=opponent_side(side),
            turn=state.turn + 1,
            case_id=state.case_id,
            history=history,
            hidden_markers=state.hidden_markers,
        ),
        {"applied": True, "captured": captured, **scored},
    )


def visible_greedy_move(observation: dict[str, Any]) -> str:
    side = observation.get("side")
    if side not in {"white", "black"}:
        return "a1a1"
    rows = tuple(str(row) for row in observation.get("visible_board", []))
    if len(rows) != 8 or any(len(row) != 8 for row in rows):
        return "a1a1"
    best_capture: tuple[int, str] | None = None
    first_move: str | None = None
    for row in range(8):
        for col in range(8):
            piece = rows[row][col]
            if piece in {"?", "."} or piece_side(piece) != side:
                continue
            for to_row, to_col in pseudo_legal_targets_visible(rows, row, col):
                target = rows[to_row][to_col]
                move = f"{rc_to_square(row, col)}{rc_to_square(to_row, to_col)}"
                if first_move is None and target == ".":
                    first_move = move
                if target not in {".", "?"} and piece_side(target) == opponent_side(side):
                    value = PIECE_VALUES[target.lower()]
                    if target.lower() == "k":
                        return move
                    if best_capture is None or value > best_capture[0]:
                        best_capture = (value, move)
    if best_capture is not None:
        return best_capture[1]
    return first_move or "a1a1"


def pseudo_legal_targets_visible(rows: tuple[str, ...], row: int, col: int) -> list[tuple[int, int]]:
    normalized = tuple(row_text.replace("?", "X") for row_text in rows)
    piece = normalized[row][col]
    side = piece_side(piece)
    if side is None:
        return []
    return pseudo_legal_targets(normalized, row, col)


def full_info_reference_move(state: FogState, side: str) -> str:
    best_capture: tuple[int, str] | None = None
    first_move: str | None = None
    for row in range(8):
        for col in range(8):
            piece = state.rows[row][col]
            if piece == "." or piece_side(piece) != side:
                continue
            for to_row, to_col in pseudo_legal_targets(state.rows, row, col):
                target = state.rows[to_row][to_col]
                move = f"{rc_to_square(row, col)}{rc_to_square(to_row, to_col)}"
                if first_move is None:
                    first_move = move
                if target != "." and piece_side(target) == opponent_side(side):
                    value = PIECE_VALUES[target.lower()]
                    if target.lower() == "k":
                        return move
                    if best_capture is None or value > best_capture[0]:
                        best_capture = (value, move)
    if best_capture is not None:
        return best_capture[1]
    return first_move or "a1a1"


def public_fixtures() -> list[Fixture]:
    return [
        Fixture(
            "visible_king_capture",
            FogState.from_rows(
                [
                    "....k...",
                    "........",
                    "........",
                    "........",
                    "........",
                    "........",
                    "....R...",
                    "....K...",
                ],
                case_id="visible_king_capture",
                hidden_markers=("private_marker_king_case",),
            ),
            "white",
        ),
        Fixture("opening_white", FogState.start(), "white"),
        Fixture(
            "hidden_equiv_alpha",
            FogState.from_rows(
                [
                    "k.......",
                    "q.......",
                    "........",
                    "........",
                    "........",
                    "........",
                    "....P...",
                    "....K...",
                ],
                case_id="hidden_equiv_alpha",
                hidden_markers=("private_marker_alpha",),
            ),
            "white",
        ),
        Fixture(
            "hidden_equiv_beta",
            FogState.from_rows(
                [
                    "k.......",
                    ".......q",
                    "........",
                    "........",
                    "........",
                    "........",
                    "....P...",
                    "....K...",
                ],
                case_id="hidden_equiv_beta",
                hidden_markers=("private_marker_beta",),
            ),
            "white",
        ),
        Fixture(
            "visible_material_capture",
            FogState.from_rows(
                [
                    ".......k",
                    ".....q..",
                    "........",
                    "........",
                    "..B.....",
                    "........",
                    "....P...",
                    "....K...",
                ],
                case_id="visible_material_capture",
                hidden_markers=("private_marker_material",),
            ),
            "white",
        ),
    ]


def rows_from_pieces(pieces: dict[str, str]) -> list[str]:
    rows = [["." for _ in range(8)] for _ in range(8)]
    for square, piece in pieces.items():
        row, col = square_to_rc(square)
        rows[row][col] = piece
    return ["".join(row) for row in rows]


def generate_fixture_suite(seed: int, scale: int = 3) -> list[Fixture]:
    rng = random.Random(seed)
    fixtures = list(public_fixtures())
    scale = max(1, int(scale))
    files = list(FILES)
    for index in range(scale):
        file_name = files[(index + rng.randrange(len(files))) % len(files)]
        fixtures.append(
            Fixture(
                f"generated_white_rook_king_{index:03d}",
                FogState.from_rows(
                    rows_from_pieces({"h1": "K", f"{file_name}2": "R", f"{file_name}8": "k"}),
                    side_to_move="white",
                    case_id=f"generated_white_rook_king_{index:03d}",
                    hidden_markers=(f"private_marker_generated_wrk_{index:03d}",),
                ),
                "white",
            )
        )

        file_name = files[(index * 3 + rng.randrange(len(files))) % len(files)]
        fixtures.append(
            Fixture(
                f"generated_black_rook_king_{index:03d}",
                FogState.from_rows(
                    rows_from_pieces({"a8": "k", f"{file_name}7": "r", f"{file_name}1": "K"}),
                    side_to_move="black",
                    case_id=f"generated_black_rook_king_{index:03d}",
                    hidden_markers=(f"private_marker_generated_brk_{index:03d}",),
                ),
                "black",
            )
        )

        knight_from, queen_to = rng.choice([("e4", "f6"), ("d4", "f5"), ("c3", "d5"), ("f3", "h4")])
        fixtures.append(
            Fixture(
                f"generated_white_knight_material_{index:03d}",
                FogState.from_rows(
                    rows_from_pieces({"a1": "K", knight_from: "N", queen_to: "q", "h8": "k"}),
                    side_to_move="white",
                    case_id=f"generated_white_knight_material_{index:03d}",
                    hidden_markers=(f"private_marker_generated_wkm_{index:03d}",),
                ),
                "white",
            )
        )

        hidden_square = rng.choice(["a7", "h7", "b6", "g6"])
        fixtures.append(
            Fixture(
                f"generated_hidden_pawn_push_{index:03d}",
                FogState.from_rows(
                    rows_from_pieces({"e1": "K", "e2": "P", "a8": "k", hidden_square: "q"}),
                    side_to_move="white",
                    case_id=f"generated_hidden_pawn_push_{index:03d}",
                    hidden_markers=(f"private_marker_generated_hpp_{index:03d}",),
                ),
                "white",
            )
        )
    return fixtures


def static_audit_candidate(candidate: Path) -> str | None:
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"read_error: {exc}"
    lowered = text.lower()
    for token in FORBIDDEN_CANDIDATE_TOKENS:
        if token in lowered:
            return f"forbidden_token: {token}"
    hidden_field = hidden_observation_field_access(text)
    if hidden_field is not None:
        return f"forbidden_observation_field: {hidden_field}"
    return None


def hidden_observation_field_access(text: str) -> str | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in FORBIDDEN_OBSERVATION_FIELDS:
            return node.value
    return None


def evaluate_candidate(
    candidate: Path,
    fixtures: list[Fixture] | None = None,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    fixtures = fixtures or public_fixtures()
    static_reject = static_audit_candidate(candidate)
    if static_reject:
        return {
            "candidate": str(candidate),
            "score": 0.0,
            "case_count": 0,
            "illegal_count": 0,
            "timeout_count": 0,
            "details": {"static_reject": static_reject},
        }

    observations = [fixture.state.observe(fixture.side) for fixture in fixtures]
    payload = "\n".join(json.dumps(observation, sort_keys=True) for observation in observations) + "\n"
    try:
        proc = subprocess.run(
            [sys.executable, str(candidate)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "candidate": str(candidate),
            "score": 0.0,
            "case_count": len(fixtures),
            "illegal_count": 0,
            "timeout_count": len(fixtures),
            "details": {"runtime_error": "timeout", "stderr": (exc.stderr or "")[:MAX_OUTPUT_CHARS]},
        }

    if proc.returncode != 0:
        return {
            "candidate": str(candidate),
            "score": 0.0,
            "case_count": len(fixtures),
            "illegal_count": 0,
            "timeout_count": 0,
            "details": {
                "runtime_error": f"returncode:{proc.returncode}",
                "stdout": proc.stdout[:MAX_OUTPUT_CHARS],
                "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
            },
        }

    outputs = proc.stdout.splitlines()
    details: list[dict[str, Any]] = []
    scores: list[float] = []
    illegal_count = 0
    leak_count = 0
    for index, fixture in enumerate(fixtures):
        move = outputs[index].strip() if index < len(outputs) else ""
        scored = score_attempt(fixture.state, fixture.side, move)
        if scored["reason"].startswith("illegal"):
            illegal_count += 1
        scores.append(float(scored["score"]))
        public_text = serialize_observation(observations[index]) + "\n" + move
        leak_hits = leak_markers(public_text, fixture)
        leak_count += len(leak_hits)
        details.append(
            {
                "case_id": fixture.name,
                "move": move,
                "score": scored["score"],
                "reason": scored["reason"],
                "leak_hits": leak_hits,
            }
        )
    if len(outputs) < len(fixtures):
        illegal_count += len(fixtures) - len(outputs)
    if len(outputs) > len(fixtures):
        leak_count += len(outputs) - len(fixtures)

    base_score = 100.0 * (sum(scores) / len(scores)) if scores else 0.0
    if leak_count:
        base_score = 0.0
    return {
        "candidate": str(candidate),
        "score": round(base_score, 4),
        "case_count": len(fixtures),
        "illegal_count": illegal_count,
        "timeout_count": 0,
        "details": {
            "leak_count": leak_count,
            "cases": details,
            "stdout_extra_line_count": max(0, len(outputs) - len(fixtures)),
            "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
        },
    }


def command_for_executable(path: Path) -> list[str]:
    if path.suffix.lower() == ".py":
        return [sys.executable, str(path)]
    return [str(path)]


def board_to_fen(state: FogState) -> str:
    fen_rows: list[str] = []
    for row in state.rows:
        out = []
        empty_count = 0
        for piece in row:
            if piece == ".":
                empty_count += 1
                continue
            if empty_count:
                out.append(str(empty_count))
                empty_count = 0
            out.append(piece)
        if empty_count:
            out.append(str(empty_count))
        fen_rows.append("".join(out) or "8")
    side = "w" if state.side_to_move == "white" else "b"
    fullmove = max(1, (state.turn // 2) + 1)
    return f"{'/'.join(fen_rows)} {side} - - 0 {fullmove}"


def run_stockfish_bestmove(
    stockfish: Path,
    state: FogState,
    movetime_ms: int = 20,
    timeout_s: float = 2.0,
) -> tuple[str, dict[str, Any]]:
    fen = board_to_fen(state)
    commands = "\n".join(
        [
            "uci",
            "isready",
            "ucinewgame",
            f"position fen {fen}",
            f"go movetime {max(1, int(movetime_ms))}",
            "quit",
            "",
        ]
    )
    try:
        proc = subprocess.run(
            command_for_executable(stockfish),
            input=commands,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return "", {"runtime_error": "timeout", "stderr": (exc.stderr or "")[:MAX_OUTPUT_CHARS], "fen": fen}
    except OSError as exc:
        return "", {"runtime_error": f"spawn_error: {exc}", "fen": fen}

    bestmove = ""
    for line in proc.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "bestmove":
            bestmove = "" if parts[1] == "(none)" else parts[1]
    return bestmove, {
        "returncode": proc.returncode,
        "fen": fen,
        "stdout": proc.stdout[:MAX_OUTPUT_CHARS],
        "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
    }


def run_observation_agent_move(
    agent: Path,
    observation: dict[str, Any],
    timeout_s: float = 2.0,
) -> tuple[str, dict[str, Any]]:
    payload = json.dumps(observation, sort_keys=True) + "\n"
    try:
        proc = subprocess.run(
            command_for_executable(agent),
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return "", {"runtime_error": "timeout", "stderr": (exc.stderr or "")[:MAX_OUTPUT_CHARS]}
    except OSError as exc:
        return "", {"runtime_error": f"spawn_error: {exc}"}

    lines = proc.stdout.splitlines()
    move = lines[0].strip() if lines else ""
    meta: dict[str, Any] = {
        "returncode": proc.returncode,
        "stdout_extra_line_count": max(0, len(lines) - 1),
        "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
    }
    if proc.returncode != 0:
        meta["runtime_error"] = f"returncode:{proc.returncode}"
    return move, meta


def king_capture_available(state: FogState, side: str) -> bool:
    for row in range(8):
        for col in range(8):
            piece = state.rows[row][col]
            if piece == "." or piece_side(piece) != side:
                continue
            for to_row, to_col in pseudo_legal_targets(state.rows, row, col):
                target = state.rows[to_row][to_col]
                if target.lower() == "k" and piece_side(target) == opponent_side(side):
                    return True
    return False


def material_balance(state: FogState, side: str) -> int:
    own = 0
    opponent = 0
    for row in state.rows:
        for piece in row:
            if piece == "." or piece.lower() == "k":
                continue
            value = PIECE_VALUES[piece.lower()]
            if piece_side(piece) == side:
                own += value
            else:
                opponent += value
    return own - opponent


def stress_case_score(
    result: str,
    plies: int,
    max_plies: int,
    material_loss: int,
    invalid: bool,
) -> float:
    if invalid:
        return 0.0
    if result == "opponent_king_captured":
        return 1.0
    survival = min(1.0, plies / max(1, max_plies))
    material = 1.0 / (1.0 + max(0, material_loss))
    if result == "max_plies":
        return 0.65 + 0.35 * material
    if result == "own_king_captured":
        return 0.35 * survival + 0.15 * material
    return 0.45 * survival + 0.25 * material


def evaluate_full_info_stockfish_stress(
    fog_agent: Path,
    stockfish: Path,
    fixtures: list[Fixture] | None = None,
    max_plies: int = 40,
    movetime_ms: int = 20,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    fixtures = fixtures or public_fixtures()
    max_plies = max(1, int(max_plies))
    cases: list[dict[str, Any]] = []
    scores: list[float] = []
    illegal_count = 0
    timeout_count = 0
    leak_count = 0
    stockfish_illegal_count = 0
    stockfish_timeout_count = 0

    for fixture in fixtures:
        state = fixture.state
        our_side = fixture.side
        start_balance = material_balance(state, our_side)
        plies = 0
        fog_move_count = 0
        stockfish_move_count = 0
        case_leak_hits: list[str] = []
        moves: list[dict[str, Any]] = []
        result = "max_plies"
        invalid = False

        for _ in range(max_plies):
            side = state.side_to_move
            if side == our_side:
                observation = state.observe(our_side)
                move, meta = run_observation_agent_move(fog_agent, observation, timeout_s=timeout_s)
                public_text = serialize_observation(observation) + "\n" + move
                leak_hits = leak_markers(public_text, fixture)
                case_leak_hits.extend(leak_hits)
                if leak_hits:
                    leak_count += len(leak_hits)
                    invalid = True
                    result = "candidate_leak"
                    moves.append({"side": side, "actor": "fog_agent", "move": move, "reason": result})
                    break
                if meta.get("runtime_error") == "timeout":
                    timeout_count += 1
                    invalid = True
                    result = "candidate_timeout"
                    moves.append({"side": side, "actor": "fog_agent", "move": move, "reason": result})
                    break
                if meta.get("runtime_error"):
                    invalid = True
                    result = "candidate_runtime_error"
                    moves.append({"side": side, "actor": "fog_agent", "move": move, "reason": result})
                    break
                next_state, applied = apply_pseudo_legal_move(state, side, move)
                if not applied["applied"]:
                    illegal_count += 1
                    invalid = True
                    result = str(applied["reason"])
                    moves.append({"side": side, "actor": "fog_agent", "move": move, "reason": result})
                    break
                state = next_state
                plies += 1
                fog_move_count += 1
                moves.append({"side": side, "actor": "fog_agent", "move": move, "reason": applied["reason"]})
                if applied["reason"] == "king_capture":
                    result = "opponent_king_captured"
                    break
                continue

            move, meta = run_stockfish_bestmove(stockfish, state, movetime_ms=movetime_ms, timeout_s=timeout_s)
            if meta.get("runtime_error") == "timeout":
                stockfish_timeout_count += 1
                result = "stockfish_timeout"
                moves.append({"side": side, "actor": "stockfish_full_info", "move": move, "reason": result})
                break
            if meta.get("runtime_error"):
                result = "stockfish_runtime_error"
                moves.append({"side": side, "actor": "stockfish_full_info", "move": move, "reason": result})
                break
            next_state, applied = apply_pseudo_legal_move(state, side, move)
            if not applied["applied"]:
                stockfish_illegal_count += 1
                result = str(applied["reason"])
                moves.append({"side": side, "actor": "stockfish_full_info", "move": move, "reason": result})
                break
            state = next_state
            plies += 1
            stockfish_move_count += 1
            moves.append({"side": side, "actor": "stockfish_full_info", "move": move, "reason": applied["reason"]})
            if applied["reason"] == "king_capture":
                result = "own_king_captured"
                break

        material_loss = max(0, start_balance - material_balance(state, our_side))
        case_score = stress_case_score(result, plies, max_plies, material_loss, invalid=invalid)
        scores.append(case_score)
        cases.append(
            {
                "case_id": fixture.name,
                "our_side": our_side,
                "result": result,
                "score": round(100.0 * case_score, 4),
                "plies": plies,
                "fog_move_count": fog_move_count,
                "stockfish_move_count": stockfish_move_count,
                "material_loss": material_loss,
                "leak_hits": sorted(set(case_leak_hits)),
                "moves": moves,
            }
        )

    return {
        "candidate": "fow_vs_full_info_stockfish",
        "score": round(100.0 * (sum(scores) / len(scores)), 4) if scores else 0.0,
        "case_count": len(fixtures),
        "illegal_count": illegal_count,
        "timeout_count": timeout_count,
        "details": {
            "visibility": "observation_only_vs_full_info_stockfish",
            "stress_type": "asymmetric_full_info_adversary",
            "fog_agent": str(fog_agent),
            "stockfish": str(stockfish),
            "movetime_ms": max(1, int(movetime_ms)),
            "max_plies": max_plies,
            "leak_count": leak_count,
            "stockfish_illegal_count": stockfish_illegal_count,
            "stockfish_timeout_count": stockfish_timeout_count,
            "cases": cases,
        },
    }


def evaluate_stockfish_reference(
    stockfish: Path,
    fixtures: list[Fixture] | None = None,
    movetime_ms: int = 20,
    timeout_s: float = 2.0,
) -> dict[str, Any]:
    fixtures = fixtures or public_fixtures()
    scores: list[float] = []
    cases: list[dict[str, Any]] = []
    illegal_count = 0
    timeout_count = 0
    unsupported_count = 0
    for fixture in fixtures:
        if king_capture_available(fixture.state, fixture.side):
            unsupported_count += 1
            scores.append(0.0)
            cases.append(
                {
                    "case_id": fixture.name,
                    "move": "",
                    "score": 0.0,
                    "reason": "unsupported_king_capture_variant",
                    "fen": board_to_fen(fixture.state),
                    "runtime_error": None,
                }
            )
            continue
        move, meta = run_stockfish_bestmove(stockfish, fixture.state, movetime_ms=movetime_ms, timeout_s=timeout_s)
        scored = score_attempt(fixture.state, fixture.side, move)
        scores.append(float(scored["score"]))
        if scored["reason"].startswith("illegal"):
            illegal_count += 1
        if meta.get("runtime_error") == "timeout":
            timeout_count += 1
        cases.append(
            {
                "case_id": fixture.name,
                "move": move,
                "score": scored["score"],
                "reason": scored["reason"],
                "fen": meta.get("fen"),
                "runtime_error": meta.get("runtime_error"),
            }
        )
    return {
        "candidate": "stockfish_full_info_reference",
        "score": round(100.0 * (sum(scores) / len(scores)), 4) if scores else 0.0,
        "case_count": len(fixtures),
        "illegal_count": illegal_count,
        "timeout_count": timeout_count,
        "details": {
            "visibility": "full_info_stockfish_reference",
            "path": str(stockfish),
            "movetime_ms": max(1, int(movetime_ms)),
            "unsupported_count": unsupported_count,
            "cases": cases,
        },
    }


def evaluate_external_jsonl_agent(
    agent: Path,
    fixtures: list[Fixture] | None = None,
    timeout_s: float = 2.0,
    label: str = "stockfish_fog_observation_agent",
) -> dict[str, Any]:
    fixtures = fixtures or public_fixtures()
    observations = [fixture.state.observe(fixture.side) for fixture in fixtures]
    payload = "\n".join(json.dumps(observation, sort_keys=True) for observation in observations) + "\n"
    try:
        proc = subprocess.run(
            command_for_executable(agent),
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "candidate": label,
            "score": 0.0,
            "case_count": len(fixtures),
            "illegal_count": 0,
            "timeout_count": len(fixtures),
            "details": {
                "visibility": "observation_only_external_agent",
                "path": str(agent),
                "runtime_error": "timeout",
                "stderr": (exc.stderr or "")[:MAX_OUTPUT_CHARS],
            },
        }
    except OSError as exc:
        return {
            "candidate": label,
            "score": 0.0,
            "case_count": len(fixtures),
            "illegal_count": 0,
            "timeout_count": 0,
            "details": {
                "visibility": "observation_only_external_agent",
                "path": str(agent),
                "runtime_error": f"spawn_error: {exc}",
            },
        }

    if proc.returncode != 0:
        return {
            "candidate": label,
            "score": 0.0,
            "case_count": len(fixtures),
            "illegal_count": 0,
            "timeout_count": 0,
            "details": {
                "visibility": "observation_only_external_agent",
                "path": str(agent),
                "runtime_error": f"returncode:{proc.returncode}",
                "stdout": proc.stdout[:MAX_OUTPUT_CHARS],
                "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
            },
        }

    outputs = proc.stdout.splitlines()
    details: list[dict[str, Any]] = []
    scores: list[float] = []
    illegal_count = 0
    leak_count = 0
    for index, fixture in enumerate(fixtures):
        move = outputs[index].strip() if index < len(outputs) else ""
        scored = score_attempt(fixture.state, fixture.side, move)
        if scored["reason"].startswith("illegal"):
            illegal_count += 1
        scores.append(float(scored["score"]))
        public_text = serialize_observation(observations[index]) + "\n" + move
        leak_hits = leak_markers(public_text, fixture)
        leak_count += len(leak_hits)
        details.append(
            {
                "case_id": fixture.name,
                "move": move,
                "score": scored["score"],
                "reason": scored["reason"],
                "leak_hits": leak_hits,
            }
        )
    if len(outputs) < len(fixtures):
        illegal_count += len(fixtures) - len(outputs)
    if len(outputs) > len(fixtures):
        leak_count += len(outputs) - len(fixtures)

    base_score = 100.0 * (sum(scores) / len(scores)) if scores else 0.0
    if leak_count:
        base_score = 0.0
    return {
        "candidate": label,
        "score": round(base_score, 4),
        "case_count": len(fixtures),
        "illegal_count": illegal_count,
        "timeout_count": 0,
        "details": {
            "visibility": "observation_only_external_agent",
            "path": str(agent),
            "leak_count": leak_count,
            "cases": details,
            "stdout_extra_line_count": max(0, len(outputs) - len(fixtures)),
            "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
        },
    }


def leak_markers(public_text: str, fixture: Fixture) -> list[str]:
    lowered = public_text.lower()
    hits: list[str] = []
    for token in PUBLIC_LEAK_TOKENS:
        if token in lowered:
            hits.append(token)
    for marker in fixture.state.hidden_markers:
        if marker and marker.lower() in lowered:
            hits.append(marker)
    return sorted(set(hits))


def evaluate_baselines(fixtures: list[Fixture] | None = None) -> list[dict[str, Any]]:
    fixtures = fixtures or public_fixtures()
    rows: list[dict[str, Any]] = []
    for name, chooser, visibility in [
        ("observation_greedy", lambda fixture: visible_greedy_move(fixture.state.observe(fixture.side)), "observation_only"),
        ("full_info_reference", lambda fixture: full_info_reference_move(fixture.state, fixture.side), "full_info_evaluator_reference"),
    ]:
        scores: list[float] = []
        cases: list[dict[str, Any]] = []
        illegal_count = 0
        for fixture in fixtures:
            move = chooser(fixture)
            scored = score_attempt(fixture.state, fixture.side, move)
            scores.append(float(scored["score"]))
            if scored["reason"].startswith("illegal"):
                illegal_count += 1
            cases.append({"case_id": fixture.name, "move": move, "score": scored["score"], "reason": scored["reason"]})
        rows.append(
            {
                "candidate": name,
                "score": round(100.0 * (sum(scores) / len(scores)), 4) if scores else 0.0,
                "case_count": len(fixtures),
                "illegal_count": illegal_count,
                "timeout_count": 0,
                "details": {"visibility": visibility, "cases": cases},
            }
        )
    return rows


def smoke_summary() -> dict[str, Any]:
    fixtures = public_fixtures()
    state_a = FogState.from_rows(
        [
            "k.......",
            "q.......",
            "........",
            "........",
            "........",
            "........",
            "....R...",
            "....K...",
        ],
        case_id="hidden_equivalence_audit",
    )
    state_b = FogState.from_rows(
        [
            "k.......",
            ".......q",
            "........",
            "........",
            "........",
            "........",
            "....R...",
            "....K...",
        ],
        case_id="hidden_equivalence_audit",
    )
    obs_a = serialize_observation(state_a.observe("white"))
    obs_b = serialize_observation(state_b.observe("white"))
    return {
        "benchmark": "fog-chess-loop",
        "case_count": len(fixtures),
        "cases": [fixture.name for fixture in fixtures],
        "anti_cheat": {
            "hidden_equivalent_observations_identical": obs_a == obs_b,
            "forbidden_observation_fields": ["canonical_board", "full_board", "legal_moves"],
        },
        "baselines": evaluate_baselines(fixtures),
    }


def example_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "benchmarks" / "data" / "fog-chess-loop" / "examples"


def evaluate_included_examples(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for candidate in sorted(example_dir().glob("*.py")):
        row = evaluate_candidate(candidate, fixtures=public_fixtures())
        rows.append(row)
        write_json(out_dir / f"{candidate.stem}.json", row)
    summary = {
        "benchmark": "fog-chess-loop",
        "candidate_count": len(rows),
        "rows": rows,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def compare_references(
    out_dir: Path,
    stockfish: Path | None = None,
    stockfish_fog_agent: Path | None = None,
    html_fog_agent: Path | None = None,
    movetime_ms: int = 20,
    timeout_s: float = 2.0,
    generated_seed: int | None = None,
    generated_scale: int = 3,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if generated_seed is None:
        fixtures = public_fixtures()
        suite = {"kind": "public"}
    else:
        fixtures = generate_fixture_suite(seed=generated_seed, scale=generated_scale)
        suite = {"kind": "generated", "seed": generated_seed, "scale": generated_scale}
    rows = evaluate_baselines(fixtures)
    if stockfish is not None:
        rows.append(evaluate_stockfish_reference(stockfish, fixtures, movetime_ms=movetime_ms, timeout_s=timeout_s))
    if stockfish_fog_agent is not None:
        rows.append(evaluate_external_jsonl_agent(stockfish_fog_agent, fixtures, timeout_s=timeout_s))
    if html_fog_agent is not None:
        rows.append(
            evaluate_external_jsonl_agent(
                html_fog_agent,
                fixtures,
                timeout_s=timeout_s,
                label="html_fog_observation_agent",
            )
        )

    for row in rows:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in row["candidate"])
        write_json(out_dir / f"{safe_name}.json", row)
    summary = {
        "benchmark": "fog-chess-loop",
        "suite": suite,
        "case_count": len(fixtures),
        "rows": rows,
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def stress_references(
    out_dir: Path,
    fog_agent: Path,
    stockfish: Path,
    movetime_ms: int = 20,
    timeout_s: float = 2.0,
    max_plies: int = 40,
    generated_seed: int | None = None,
    generated_scale: int = 3,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if generated_seed is None:
        fixtures = public_fixtures()
        suite = {"kind": "stress", "fixture_source": "public"}
    else:
        fixtures = generate_fixture_suite(seed=generated_seed, scale=generated_scale)
        suite = {
            "kind": "stress",
            "fixture_source": "generated",
            "seed": generated_seed,
            "scale": generated_scale,
        }
    row = evaluate_full_info_stockfish_stress(
        fog_agent,
        stockfish,
        fixtures=fixtures,
        max_plies=max_plies,
        movetime_ms=movetime_ms,
        timeout_s=timeout_s,
    )
    write_json(out_dir / "fow_vs_full_info_stockfish.json", row)
    summary = {
        "benchmark": "fog-chess-loop",
        "suite": suite,
        "case_count": len(fixtures),
        "rows": [row],
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fog-of-War Chess partial-observation benchmark runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--out-dir", type=Path, required=True)

    eval_included = subparsers.add_parser("eval-included")
    eval_included.add_argument("--out-dir", type=Path, required=True)

    evaluate = subparsers.add_parser("eval")
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--out", type=Path, required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--out-dir", type=Path, required=True)
    compare.add_argument("--stockfish", type=Path)
    compare.add_argument("--stockfish-fog-agent", type=Path)
    compare.add_argument("--html-fog-agent", type=Path)
    compare.add_argument("--movetime-ms", type=int, default=20)
    compare.add_argument("--timeout-s", type=float, default=2.0)
    compare.add_argument("--generated-seed", type=int)
    compare.add_argument("--generated-scale", type=int, default=3)

    stress = subparsers.add_parser("stress")
    stress.add_argument("--out-dir", type=Path, required=True)
    stress.add_argument("--fog-agent", type=Path, required=True)
    stress.add_argument("--stockfish", type=Path, required=True)
    stress.add_argument("--movetime-ms", type=int, default=20)
    stress.add_argument("--timeout-s", type=float, default=2.0)
    stress.add_argument("--max-plies", type=int, default=40)
    stress.add_argument("--generated-seed", type=int)
    stress.add_argument("--generated-scale", type=int, default=3)

    args = parser.parse_args(argv)
    if args.command == "smoke":
        args.out_dir.mkdir(parents=True, exist_ok=True)
        summary = smoke_summary()
        write_json(args.out_dir / "summary.json", summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "eval-included":
        summary = evaluate_included_examples(args.out_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "eval":
        row = evaluate_candidate(args.candidate)
        write_json(args.out, row)
        print(json.dumps(row, indent=2, sort_keys=True))
        return 0
    if args.command == "compare":
        summary = compare_references(
            args.out_dir,
            stockfish=args.stockfish,
            stockfish_fog_agent=args.stockfish_fog_agent,
            html_fog_agent=args.html_fog_agent,
            movetime_ms=args.movetime_ms,
            timeout_s=args.timeout_s,
            generated_seed=args.generated_seed,
            generated_scale=args.generated_scale,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.command == "stress":
        summary = stress_references(
            args.out_dir,
            fog_agent=args.fog_agent,
            stockfish=args.stockfish,
            movetime_ms=args.movetime_ms,
            timeout_s=args.timeout_s,
            max_plies=args.max_plies,
            generated_seed=args.generated_seed,
            generated_scale=args.generated_scale,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

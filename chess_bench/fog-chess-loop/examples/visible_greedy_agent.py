#!/usr/bin/env python3
from __future__ import annotations

import json
import sys


FILES = "abcdefgh"
VALUES = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9, "k": 100}


def side_of(piece):
    if piece in "PNBRQK":
        return "white"
    if piece in "pnbrqk":
        return "black"
    return None


def rc_to_square(row, col):
    return FILES[col] + str(8 - row)


def in_bounds(row, col):
    return 0 <= row < 8 and 0 <= col < 8


def targets(rows, row, col):
    piece = rows[row][col]
    side = side_of(piece)
    if side is None:
        return []
    lower = piece.lower()
    if lower == "p":
        direction = -1 if side == "white" else 1
        out = []
        one = row + direction
        if in_bounds(one, col) and rows[one][col] == ".":
            out.append((one, col))
            two = row + 2 * direction
            start = 6 if side == "white" else 1
            if row == start and in_bounds(two, col) and rows[two][col] == ".":
                out.append((two, col))
        for dc in (-1, 1):
            nr, nc = row + direction, col + dc
            if in_bounds(nr, nc) and side_of(rows[nr][nc]) not in {None, side}:
                out.append((nr, nc))
        return out
    if lower == "n":
        return leap(rows, row, col, side, [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)])
    if lower == "k":
        return leap(rows, row, col, side, [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)])
    if lower == "b":
        return slide(rows, row, col, side, [(-1, -1), (-1, 1), (1, -1), (1, 1)])
    if lower == "r":
        return slide(rows, row, col, side, [(-1, 0), (1, 0), (0, -1), (0, 1)])
    if lower == "q":
        return slide(rows, row, col, side, [(-1, -1), (-1, 1), (1, -1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)])
    return []


def leap(rows, row, col, side, deltas):
    out = []
    for dr, dc in deltas:
        nr, nc = row + dr, col + dc
        if in_bounds(nr, nc) and side_of(rows[nr][nc]) != side:
            out.append((nr, nc))
    return out


def slide(rows, row, col, side, deltas):
    out = []
    for dr, dc in deltas:
        nr, nc = row + dr, col + dc
        while in_bounds(nr, nc):
            target_side = side_of(rows[nr][nc])
            if rows[nr][nc] == "?":
                break
            if target_side == side:
                break
            out.append((nr, nc))
            if target_side is not None:
                break
            nr += dr
            nc += dc
    return out


def choose(obs):
    side = obs["side"]
    rows = obs["visible_board"]
    best = None
    first = None
    for row in range(8):
        for col in range(8):
            piece = rows[row][col]
            if side_of(piece) != side:
                continue
            for tr, tc in targets(rows, row, col):
                target = rows[tr][tc]
                move = rc_to_square(row, col) + rc_to_square(tr, tc)
                if first is None and target == ".":
                    first = move
                if side_of(target) not in {None, side}:
                    if target.lower() == "k":
                        return move
                    score = VALUES[target.lower()]
                    if best is None or score > best[0]:
                        best = (score, move)
    if best is not None:
        return best[1]
    return first or "e2e4"


for line in sys.stdin:
    print(choose(json.loads(line)), flush=True)

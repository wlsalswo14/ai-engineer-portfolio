#!/usr/bin/env python3
import sys
import time

FILES = "abcdefgh"
RANKS = "12345678"

PIECE_VALUES = {
    "P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0,
    "p": -100, "n": -320, "b": -330, "r": -500, "q": -900, "k": 0,
}

KNIGHT_DELTAS = (-17, -15, -10, -6, 6, 10, 15, 17)
BISHOP_DELTAS = (-9, -7, 7, 9)
ROOK_DELTAS = (-8, -1, 1, 8)
KING_DELTAS = (-9, -8, -7, -1, 1, 7, 8, 9)


def sq_to_idx(sq):
    return (int(sq[1]) - 1) * 8 + FILES.index(sq[0])


def idx_to_sq(i):
    return FILES[i % 8] + RANKS[i // 8]


def color_of(piece):
    if piece == ".":
        return None
    return "w" if piece.isupper() else "b"


def inside(i):
    return 0 <= i < 64


class Position:
    def __init__(self):
        self.board = ["."] * 64
        self.side = "w"
        self.castling = "-"
        self.ep = "-"
        self.halfmove = 0
        self.fullmove = 1

    def clone(self):
        p = Position()
        p.board = self.board[:]
        p.side = self.side
        p.castling = self.castling
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        return p


def set_startpos(pos):
    return parse_fen(START_FEN)


def parse_fen(fen):
    pos = Position()
    parts = fen.split()
    rows = parts[0].split("/")
    for r, row in enumerate(rows[::-1]):
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                pos.board[r * 8 + f] = ch
                f += 1
    pos.side = parts[1]
    pos.castling = parts[2]
    pos.ep = parts[3]
    pos.halfmove = int(parts[4])
    pos.fullmove = int(parts[5])
    return pos


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def start_position():
    return parse_fen(START_FEN)


def king_square(board, side):
    target = "K" if side == "w" else "k"
    for i, p in enumerate(board):
        if p == target:
            return i
    return -1


def attacked(board, sq, by_side):
    if by_side == "w":
        for d in (-7, -9):
            i = sq + d
            if inside(i) and board[i] == "P":
                if d == -7 and sq % 8 != 0:
                    return True
                if d == -9 and sq % 8 != 7:
                    return True
    else:
        for d in (7, 9):
            i = sq + d
            if inside(i) and board[i] == "p":
                if d == 7 and sq % 8 != 7:
                    return True
                if d == 9 and sq % 8 != 0:
                    return True

    knight = "N" if by_side == "w" else "n"
    for d in KNIGHT_DELTAS:
        i = sq + d
        if not inside(i):
            continue
        if abs((i % 8) - (sq % 8)) > 2:
            continue
        if board[i] == knight:
            return True

    bishop = ("B", "Q") if by_side == "w" else ("b", "q")
    rook = ("R", "Q") if by_side == "w" else ("r", "q")
    king = "K" if by_side == "w" else "k"

    for d in BISHOP_DELTAS:
        i = sq + d
        while inside(i) and abs((i % 8) - ((i - d) % 8)) == 1:
            piece = board[i]
            if piece != ".":
                if piece in bishop:
                    return True
                break
            i += d

    for d in ROOK_DELTAS:
        i = sq + d
        while inside(i):
            if d == -1 or d == 1:
                if abs((i % 8) - ((i - d) % 8)) != 1:
                    break
            piece = board[i]
            if piece != ".":
                if piece in rook:
                    return True
                break
            i += d

    for d in KING_DELTAS:
        i = sq + d
        if not inside(i):
            continue
        if abs((i % 8) - (sq % 8)) > 1:
            continue
        if board[i] == king:
            return True
    return False


def in_check(pos, side=None):
    if side is None:
        side = pos.side
    ksq = king_square(pos.board, side)
    return attacked(pos.board, ksq, "b" if side == "w" else "w")


def make_move(pos, move):
    fr, to, promo, flag = move
    board = pos.board[:]
    piece = board[fr]
    captured = board[to]
    board[to] = piece
    board[fr] = "."
    new_ep = "-"

    if flag == "ep":
        cap_sq = to - 8 if pos.side == "w" else to + 8
        captured = board[cap_sq]
        board[cap_sq] = "."
    elif flag == "castle":
        if to == 62:
            board[61] = board[63]
            board[63] = "."
        elif to == 58:
            board[59] = board[56]
            board[56] = "."
        elif to == 6:
            board[5] = board[7]
            board[7] = "."
        elif to == 2:
            board[3] = board[0]
            board[0] = "."

    if promo:
        board[to] = promo

    if piece == "P" and to - fr == 16:
        new_ep = idx_to_sq(fr + 8)
    elif piece == "p" and fr - to == 16:
        new_ep = idx_to_sq(fr - 8)

    castling = pos.castling
    if piece == "K":
        castling = castling.replace("K", "").replace("Q", "")
    elif piece == "k":
        castling = castling.replace("k", "").replace("q", "")
    elif fr == 0 or to == 0:
        castling = castling.replace("Q", "")
    elif fr == 7 or to == 7:
        castling = castling.replace("K", "")
    elif fr == 56 or to == 56:
        castling = castling.replace("q", "")
    elif fr == 63 or to == 63:
        castling = castling.replace("k", "")

    npos = Position()
    npos.board = board
    npos.side = "b" if pos.side == "w" else "w"
    npos.castling = castling if castling else "-"
    npos.ep = new_ep
    npos.halfmove = 0 if piece.lower() == "p" or captured != "." else pos.halfmove + 1
    npos.fullmove = pos.fullmove + (1 if pos.side == "b" else 0)
    return npos


def pseudo_moves(pos):
    side = pos.side
    board = pos.board
    enemy = "b" if side == "w" else "w"
    for i, piece in enumerate(board):
        if piece == "." or color_of(piece) != side:
            continue
        r, f = divmod(i, 8)
        if piece.lower() == "p":
            dir = 8 if side == "w" else -8
            start_rank = 1 if side == "w" else 6
            promo_rank = 6 if side == "w" else 1
            one = i + dir
            if inside(one) and board[one] == ".":
                if r == promo_rank:
                    for p in ("Q", "R", "B", "N"):
                        yield (i, one, p if side == "w" else p.lower(), None)
                else:
                    yield (i, one, None, None)
                    two = i + 2 * dir
                    if r == start_rank and board[two] == ".":
                        yield (i, two, None, None)
            for cap_dir in (dir - 1, dir + 1):
                to = i + cap_dir
                if not inside(to):
                    continue
                if abs((to % 8) - f) != 1:
                    continue
                target = board[to]
                if target != "." and color_of(target) == enemy:
                    if r == promo_rank:
                        for p in ("Q", "R", "B", "N"):
                            yield (i, to, p if side == "w" else p.lower(), None)
                    else:
                        yield (i, to, None, None)
                elif pos.ep != "-" and to == sq_to_idx(pos.ep):
                    yield (i, to, None, "ep")
            continue
        if piece.lower() == "n":
            for d in KNIGHT_DELTAS:
                to = i + d
                if not inside(to) or abs((to % 8) - f) > 2:
                    continue
                target = board[to]
                if target == "." or color_of(target) == enemy:
                    yield (i, to, None, None)
            continue
        if piece.lower() in ("b", "r", "q"):
            deltas = []
            if piece.lower() in ("b", "q"):
                deltas += BISHOP_DELTAS
            if piece.lower() in ("r", "q"):
                deltas += ROOK_DELTAS
            for d in deltas:
                to = i + d
                while inside(to):
                    if d in (-1, 1) and abs((to % 8) - ((to - d) % 8)) != 1:
                        break
                    if d in (-9, -7, 7, 9) and abs((to % 8) - ((to - d) % 8)) != 1:
                        break
                    target = board[to]
                    if target == ".":
                        yield (i, to, None, None)
                    else:
                        if color_of(target) == enemy:
                            yield (i, to, None, None)
                        break
                    to += d
            continue
        if piece.lower() == "k":
            for d in KING_DELTAS:
                to = i + d
                if not inside(to) or abs((to % 8) - f) > 1:
                    continue
                target = board[to]
                if target == "." or color_of(target) == enemy:
                    yield (i, to, None, None)
            if side == "w" and i == 4 and not in_check(pos, side):
                if "K" in pos.castling and board[5] == board[6] == "." and board[7] == "R":
                    if not attacked(board, 5, "b") and not attacked(board, 6, "b"):
                        yield (4, 6, None, "castle")
                if "Q" in pos.castling and board[3] == board[2] == board[1] == "." and board[0] == "R":
                    if not attacked(board, 3, "b") and not attacked(board, 2, "b"):
                        yield (4, 2, None, "castle")
            if side == "b" and i == 60 and not in_check(pos, side):
                if "k" in pos.castling and board[61] == board[62] == "." and board[63] == "r":
                    if not attacked(board, 61, "w") and not attacked(board, 62, "w"):
                        yield (60, 62, None, "castle")
                if "q" in pos.castling and board[59] == board[58] == board[57] == "." and board[56] == "r":
                    if not attacked(board, 59, "w") and not attacked(board, 58, "w"):
                        yield (60, 58, None, "castle")


def legal_moves(pos):
    for mv in pseudo_moves(pos):
        npos = make_move(pos, mv)
        if not in_check(npos, "b" if pos.side == "w" else "w"):
            yield mv


def move_to_uci(move):
    fr, to, promo, _ = move
    s = idx_to_sq(fr) + idx_to_sq(to)
    if promo:
        s += promo.lower()
    return s


def evaluate(pos):
    score = 0
    for i, p in enumerate(pos.board):
        if p == ".":
            continue
        score += PIECE_VALUES[p]
        if p == "P":
            score += (i // 8) * 2
        elif p == "p":
            score -= (7 - i // 8) * 2
        elif p in ("N", "n", "B", "b"):
            center = 3 - abs(3.5 - (i % 8)) + 3 - abs(3.5 - (i // 8))
            score += int(center) if p.isupper() else -int(center)
    if in_check(pos, pos.side):
        score += -15 if pos.side == "w" else 15
    return score if pos.side == "w" else -score


def ordered_moves(pos):
    moves = list(legal_moves(pos))
    scored = []
    for mv in moves:
        fr, to, promo, flag = mv
        score = 0
        target = pos.board[to]
        piece = pos.board[fr]
        if flag == "castle":
            score += 50
        if target != ".":
            score += 10 * abs(PIECE_VALUES[target]) - abs(PIECE_VALUES[piece])
        if promo:
            score += abs(PIECE_VALUES[promo]) + 800
        scored.append((score, mv))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [mv for _, mv in scored]


class SearchTimeout(Exception):
    pass


def alphabeta(pos, depth, alpha, beta, end_time):
    if time.time() >= end_time:
        raise SearchTimeout
    moves = ordered_moves(pos)
    if depth == 0 or not moves:
        if not moves:
            return (-100000 + (3 - depth)) if in_check(pos) else 0, None
        return evaluate(pos), None
    best = None
    for mv in moves:
        npos = make_move(pos, mv)
        score, _ = alphabeta(npos, depth - 1, -beta, -alpha, end_time)
        score = -score
        if score > alpha:
            alpha = score
            best = mv
        if alpha >= beta:
            break
    return alpha, best


def choose_move(pos, movetime_ms):
    legal = list(legal_moves(pos))
    if not legal:
        return None
    best = legal[0]
    end_time = time.time() + max(0.01, movetime_ms / 1000.0 - 0.005)
    depth = 1
    try:
        while True:
            score, mv = alphabeta(pos, depth, -10**9, 10**9, end_time)
            if mv is not None:
                best = mv
            depth += 1
    except SearchTimeout:
        pass
    return best


def apply_moves(pos, moves):
    for u in moves:
        found = None
        for mv in legal_moves(pos):
            if move_to_uci(mv) == u:
                found = mv
                break
        if found is None:
            return pos
        pos = make_move(pos, found)
    return pos


def handle_position(cmd, current):
    if cmd[1] == "startpos":
        pos = start_position()
        moves = []
        if len(cmd) > 2 and cmd[2] == "moves":
            moves = cmd[3:]
        return apply_moves(pos, moves)
    if cmd[1] == "fen":
        fen = " ".join(cmd[2:8])
        pos = parse_fen(fen)
        moves = []
        if len(cmd) > 8 and cmd[8] == "moves":
            moves = cmd[9:]
        return apply_moves(pos, moves)
    return current


def main():
    pos = start_position()
    for raw in sys.stdin:
        cmd = raw.strip().split()
        if not cmd:
            continue
        if cmd[0] == "uci":
            print("id name SimplePythonEngine")
            print("id author OpenAI")
            print("uciok")
            sys.stdout.flush()
        elif cmd[0] == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd[0] == "ucinewgame":
            pos = start_position()
        elif cmd[0] == "position":
            pos = handle_position(cmd, pos)
        elif cmd[0] == "go":
            movetime = 20
            if len(cmd) >= 3 and cmd[1] == "movetime":
                movetime = int(cmd[2])
            mv = choose_move(pos, movetime)
            if mv is None:
                print("bestmove 0000")
            else:
                print("bestmove", move_to_uci(mv))
            sys.stdout.flush()
        elif cmd[0] == "quit":
            break


if __name__ == "__main__":
    main()

import sys
import time


FILES = "abcdefgh"
RANKS = "12345678"
WHITE, BLACK = 0, 1
PIECE_VALUES = {
    "P": 100,
    "N": 320,
    "B": 330,
    "R": 500,
    "Q": 900,
    "K": 0,
}

KNIGHT_DELTAS = (-17, -15, -10, -6, 6, 10, 15, 17)
BISHOP_DELTAS = (-9, -7, 7, 9)
ROOK_DELTAS = (-8, -1, 1, 8)
KING_DELTAS = (-9, -8, -7, -1, 1, 7, 8, 9)

PST = {
    "P": (
        0, 0, 0, 0, 0, 0, 0, 0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, -5, -10, 0, 0, -10, -5, 5,
        5, 10, 10, -20, -20, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ),
    "N": (
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50,
    ),
    "B": (
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -20, -10, -10, -10, -10, -10, -10, -20,
    ),
    "R": (
        0, 0, 0, 5, 5, 0, 0, 0,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        5, 10, 10, 10, 10, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ),
    "Q": (
        -20, -10, -10, -5, -5, -10, -10, -20,
        -10, 0, 0, 0, 0, 5, 0, -10,
        -10, 0, 5, 5, 5, 5, 5, -10,
        -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5,
        -10, 5, 5, 5, 5, 5, 0, -10,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, -5, -5, -10, -10, -20,
    ),
    "K": (
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20,
        20, 30, 10, 0, 0, 10, 30, 20,
    ),
}


def sq_to_idx(s):
    return (int(s[1]) - 1) * 8 + (ord(s[0]) - 97)


def idx_to_sq(i):
    return FILES[i & 7] + RANKS[i >> 3]


def on_board(i):
    return 0 <= i < 64


def same_file_or_rank_or_diag(a, b, delta):
    af, ar = a & 7, a >> 3
    bf, br = b & 7, b >> 3
    if delta in (-1, 1):
        return ar == br
    if delta in (-8, 8):
        return af == bf
    if delta in (-9, 9):
        return af - ar == bf - br
    return af + ar == bf + br


def knight_ok(a, b):
    return abs((a & 7) - (b & 7)) in (1, 2) and abs((a >> 3) - (b >> 3)) in (1, 2)


def king_ok(a, b):
    return max(abs((a & 7) - (b & 7)), abs((a >> 3) - (b >> 3))) == 1


def pawn_cap_ok(a, b):
    return abs((a & 7) - (b & 7)) == 1 and abs((a >> 3) - (b >> 3)) == 1


class Position:
    __slots__ = ("board", "side", "castling", "ep", "halfmove", "fullmove", "king_sq")

    def __init__(self):
        self.board = [None] * 64
        self.side = WHITE
        self.castling = "-"
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = {WHITE: 4, BLACK: 60}

    def clone(self):
        p = Position()
        p.board = self.board[:]
        p.side = self.side
        p.castling = self.castling
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        p.king_sq = self.king_sq.copy()
        return p


def parse_fen(fen):
    p = Position()
    parts = fen.split()
    rows = parts[0].split("/")
    for r, row in enumerate(rows[::-1]):
        f = 0
        for ch in row:
            if ch.isdigit():
                f += int(ch)
            else:
                idx = r * 8 + f
                p.board[idx] = ch
                if ch == "K":
                    p.king_sq[WHITE] = idx
                elif ch == "k":
                    p.king_sq[BLACK] = idx
                f += 1
    p.side = WHITE if parts[1] == "w" else BLACK
    p.castling = parts[2]
    p.ep = -1 if parts[3] == "-" else sq_to_idx(parts[3])
    p.halfmove = int(parts[4])
    p.fullmove = int(parts[5])
    return p


STARTPOS_FEN = "rn1qkbnr/pppbpppp/8/3p4/8/1P6/PBPPPPPP/RN1QKBNR w KQkq - 0 1"


def set_startpos():
    return parse_fen("rn1qkbnr/pppbpppp/8/3p4/8/1P6/PBPPPPPP/RN1QKBNR w KQkq - 0 1")


def attacked_by(pos, sq, by_side):
    b = pos.board
    if by_side == WHITE:
        for d in (-7, -9):
            s = sq + d
            if on_board(s) and b[s] == "P" and pawn_cap_ok(s, sq):
                return True
    else:
        for d in (7, 9):
            s = sq + d
            if on_board(s) and b[s] == "p" and pawn_cap_ok(s, sq):
                return True
    for d in KNIGHT_DELTAS:
        s = sq + d
        if on_board(s) and knight_ok(s, sq):
            pc = b[s]
            if pc == ("N" if by_side == WHITE else "n"):
                return True
    for d in BISHOP_DELTAS:
        s = sq + d
        while on_board(s) and same_file_or_rank_or_diag(s - d, s, d):
            pc = b[s]
            if pc:
                if pc in (("B", "Q") if by_side == WHITE else ("b", "q")):
                    return True
                break
            s += d
    for d in ROOK_DELTAS:
        s = sq + d
        while on_board(s) and same_file_or_rank_or_diag(s - d, s, d):
            pc = b[s]
            if pc:
                if pc in (("R", "Q") if by_side == WHITE else ("r", "q")):
                    return True
                break
            s += d
    for d in KING_DELTAS:
        s = sq + d
        if on_board(s) and king_ok(s, sq):
            pc = b[s]
            if pc == ("K" if by_side == WHITE else "k"):
                return True
    return False


def in_check(pos, side):
    return attacked_by(pos, pos.king_sq[side], 1 - side)


def push_move(moves, fr, to, promo=None, flag=None):
    moves.append((fr, to, promo, flag))


def generate_pseudo(pos):
    b = pos.board
    side = pos.side
    us = "PNBRQK" if side == WHITE else "pnbrqk"
    moves = []
    for i, pc in enumerate(b):
        if pc is None or pc not in us:
            continue
        if pc in "Pp":
            dir_ = 8 if pc == "P" else -8
            start_rank = 1 if pc == "P" else 6
            promo_rank = 6 if pc == "P" else 1
            one = i + dir_
            if on_board(one) and b[one] is None:
                if (i >> 3) == promo_rank:
                    for pr in "QRBN":
                        push_move(moves, i, one, pr if pc == "P" else pr.lower())
                else:
                    push_move(moves, i, one)
                two = i + 2 * dir_
                if (i >> 3) == start_rank and b[two] is None:
                    push_move(moves, i, two, flag="dbl")
            for capd in (dir_ - 1, dir_ + 1):
                to = i + capd
                if not on_board(to) or not pawn_cap_ok(i, to):
                    continue
                target = b[to]
                if target and target.isupper() != pc.isupper():
                    if (i >> 3) == promo_rank:
                        for pr in "QRBN":
                            push_move(moves, i, to, pr if pc == "P" else pr.lower())
                    else:
                        push_move(moves, i, to)
                elif to == pos.ep:
                    push_move(moves, i, to, flag="ep")
        elif pc in "Nn":
            for d in KNIGHT_DELTAS:
                to = i + d
                if on_board(to) and knight_ok(i, to):
                    t = b[to]
                    if t is None or t.isupper() != pc.isupper():
                        push_move(moves, i, to)
        elif pc in "BbRrQq":
            deltas = BISHOP_DELTAS if pc in "Bb" else ROOK_DELTAS if pc in "Rr" else BISHOP_DELTAS + ROOK_DELTAS
            for d in deltas:
                to = i + d
                while on_board(to) and same_file_or_rank_or_diag(to - d, to, d):
                    t = b[to]
                    if t is None:
                        push_move(moves, i, to)
                    else:
                        if t.isupper() != pc.isupper():
                            push_move(moves, i, to)
                        break
                    to += d
        else:
            for d in KING_DELTAS:
                to = i + d
                if on_board(to) and king_ok(i, to):
                    t = b[to]
                    if t is None or t.isupper() != pc.isupper():
                        push_move(moves, i, to)
            if side == WHITE and i == 4:
                if "K" in pos.castling and b[5] is None and b[6] is None and not in_check(pos, WHITE) and not attacked_by(pos, 5, BLACK) and not attacked_by(pos, 6, BLACK):
                    push_move(moves, 4, 6, flag="ck")
                if "Q" in pos.castling and b[3] is None and b[2] is None and b[1] is None and not in_check(pos, WHITE) and not attacked_by(pos, 3, BLACK) and not attacked_by(pos, 2, BLACK):
                    push_move(moves, 4, 2, flag="cq")
            elif side == BLACK and i == 60:
                if "k" in pos.castling and b[61] is None and b[62] is None and not in_check(pos, BLACK) and not attacked_by(pos, 61, WHITE) and not attacked_by(pos, 62, WHITE):
                    push_move(moves, 60, 62, flag="ck")
                if "q" in pos.castling and b[59] is None and b[58] is None and b[57] is None and not in_check(pos, BLACK) and not attacked_by(pos, 59, WHITE) and not attacked_by(pos, 58, WHITE):
                    push_move(moves, 60, 58, flag="cq")
    return moves


def apply_move(pos, move):
    fr, to, promo, flag = move
    p = pos.clone()
    b = p.board
    pc = b[fr]
    cap = b[to]
    b[fr] = None
    p.ep = -1
    if pc in "Pp":
        p.halfmove = 0
        if flag == "ep":
            cap_sq = to - 8 if pc == "P" else to + 8
            cap = b[cap_sq]
            b[cap_sq] = None
        if flag == "dbl":
            p.ep = fr + (8 if pc == "P" else -8)
        if promo:
            pc = promo
    elif cap is not None:
        p.halfmove = 0
    else:
        p.halfmove += 1
    if pc in "Kk":
        p.king_sq[p.side] = to
        if p.side == WHITE:
            p.castling = p.castling.replace("K", "").replace("Q", "")
        else:
            p.castling = p.castling.replace("k", "").replace("q", "")
        if flag == "ck":
            if to == 6:
                b[5] = b[7]
                b[7] = None
            elif to == 62:
                b[61] = b[63]
                b[63] = None
        elif flag == "cq":
            if to == 2:
                b[3] = b[0]
                b[0] = None
            elif to == 58:
                b[59] = b[56]
                b[56] = None
    if fr == 0 or to == 0:
        p.castling = p.castling.replace("Q", "")
    if fr == 7 or to == 7:
        p.castling = p.castling.replace("K", "")
    if fr == 56 or to == 56:
        p.castling = p.castling.replace("q", "")
    if fr == 63 or to == 63:
        p.castling = p.castling.replace("k", "")
    b[to] = pc
    p.side ^= 1
    if p.side == WHITE:
        p.fullmove += 1
    return p


def legal_moves(pos):
    moves = []
    for mv in generate_pseudo(pos):
        np = apply_move(pos, mv)
        if not in_check(np, pos.side):
            moves.append(mv)
    return moves


def move_to_uci(move):
    fr, to, promo, _ = move
    s = idx_to_sq(fr) + idx_to_sq(to)
    if promo:
        s += promo.lower()
    return s


def evaluate(pos):
    score = 0
    for i, pc in enumerate(pos.board):
        if not pc:
            continue
        color = 1 if pc.isupper() else -1
        p = pc.upper()
        pst = PST[p][i if pc.isupper() else 63 - i]
        score += color * (PIECE_VALUES[p] + pst)
    return score if pos.side == WHITE else -score


TIME_UP = False


def search(pos, depth, alpha, beta, end_time):
    global TIME_UP
    if TIME_UP or time.perf_counter() >= end_time:
        TIME_UP = True
        return evaluate(pos)
    moves = legal_moves(pos)
    if not moves:
        if in_check(pos, pos.side):
            return -100000 + (4 - depth)
        return 0
    if depth <= 0:
        return evaluate(pos)
    best = -10**9
    moves.sort(key=lambda m: move_order(pos, m), reverse=True)
    for mv in moves:
        np = apply_move(pos, mv)
        sc = -search(np, depth - 1, -beta, -alpha, end_time)
        if TIME_UP:
            return best if best > -10**8 else sc
        if sc > best:
            best = sc
        if sc > alpha:
            alpha = sc
        if alpha >= beta:
            break
    return best


def move_order(pos, move):
    fr, to, promo, flag = move
    b = pos.board
    pc = b[fr]
    target = b[to]
    score = 0
    if flag == "ep":
        score += 105
    if target:
        score += 10 * PIECE_VALUES[target.upper()] - PIECE_VALUES[pc.upper()]
    if promo:
        score += PIECE_VALUES[promo.upper()] + 800
    if pc.upper() == "K" and abs(to - fr) == 2:
        score -= 10
    return score


def choose_move(pos, movetime_ms):
    global TIME_UP
    moves = legal_moves(pos)
    if not moves:
        return "0000"
    best = moves[0]
    best_score = -10**9
    start = time.perf_counter()
    end_time = start + max(0.001, movetime_ms / 1000.0 * 0.95)
    ordered = sorted(moves, key=lambda m: move_order(pos, m), reverse=True)
    for depth in range(1, 5):
        TIME_UP = False
        cur_best = best
        cur_score = -10**9
        alpha = -10**9
        beta = 10**9
        for mv in ordered:
            if time.perf_counter() >= end_time:
                TIME_UP = True
                break
            np = apply_move(pos, mv)
            sc = -search(np, depth - 1, -beta, -alpha, end_time)
            if TIME_UP:
                break
            if sc > cur_score:
                cur_score = sc
                cur_best = mv
            if sc > alpha:
                alpha = sc
        if not TIME_UP:
            best = cur_best
            best_score = cur_score
        if time.perf_counter() >= end_time:
            break
    return move_to_uci(best)


def parse_moves(parts, pos):
    i = 0
    while i < len(parts):
        mv = parts[i]
        if len(mv) < 4:
            break
        from_sq = sq_to_idx(mv[:2])
        to_sq = sq_to_idx(mv[2:4])
        promo = mv[4].upper() if len(mv) > 4 else None
        found = None
        for legal in legal_moves(pos):
            if legal[0] == from_sq and legal[1] == to_sq:
                if (promo is None and legal[2] is None) or (promo is not None and legal[2] and legal[2].upper() == promo):
                    found = legal
                    break
        if not found:
            break
        pos = apply_move(pos, found)
        i += 1
    return pos


def parse_position(cmd):
    parts = cmd.split()
    if parts[1] == "startpos":
        pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        if "moves" in parts:
            pos = parse_moves(parts[parts.index("moves") + 1 :], pos)
        return pos
    if parts[1] == "fen":
        fen = " ".join(parts[2:8])
        pos = parse_fen(fen)
        if len(parts) > 8 and parts[8] == "moves":
            pos = parse_moves(parts[9:], pos)
        return pos
    return parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


def main():
    pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    for raw in sys.stdin:
        cmd = raw.strip()
        if cmd == "uci":
            sys.stdout.write("id name TinyPythonEngine\n")
            sys.stdout.write("id author Codex\n")
            sys.stdout.write("uciok\n")
            sys.stdout.flush()
        elif cmd == "isready":
            sys.stdout.write("readyok\n")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        elif cmd.startswith("position "):
            pos = parse_position(cmd)
        elif cmd.startswith("go "):
            parts = cmd.split()
            mt = 20
            if "movetime" in parts:
                try:
                    mt = int(parts[parts.index("movetime") + 1])
                except Exception:
                    mt = 20
            bm = choose_move(pos, mt)
            sys.stdout.write(f"bestmove {bm}\n")
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

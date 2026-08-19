import sys
import time


WHITE, BLACK = 0, 1
FILES = "abcdefgh"
RANKS = "12345678"

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

STARTPOS = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

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


def knight_ok(a, b):
    return abs((a & 7) - (b & 7)) in (1, 2) and abs((a >> 3) - (b >> 3)) in (1, 2)


def king_ok(a, b):
    return max(abs((a & 7) - (b & 7)), abs((a >> 3) - (b >> 3))) == 1


def pawn_cap_ok(a, b):
    return abs((a & 7) - (b & 7)) == 1 and abs((a >> 3) - (b >> 3)) == 1


def ray_ok(prev_sq, sq, delta):
    pf, pr = prev_sq & 7, prev_sq >> 3
    f, r = sq & 7, sq >> 3
    if delta in (-1, 1):
        return pr == r
    if delta in (-8, 8):
        return pf == f
    if delta in (-9, 9):
        return pf - pr == f - r
    return pf + pr == f + r


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
    pos = Position()
    parts = fen.split()
    if len(parts) < 6:
        return parse_fen(STARTPOS)
    rows = parts[0].split("/")
    if len(rows) != 8:
        return parse_fen(STARTPOS)
    for fen_rank, row in enumerate(rows):
        idx_rank = 7 - fen_rank
        file_idx = 0
        for ch in row:
            if ch.isdigit():
                file_idx += int(ch)
                continue
            if 0 <= file_idx < 8:
                sq = idx_rank * 8 + file_idx
                pos.board[sq] = ch
                if ch == "K":
                    pos.king_sq[WHITE] = sq
                elif ch == "k":
                    pos.king_sq[BLACK] = sq
            file_idx += 1
    pos.side = WHITE if parts[1] == "w" else BLACK
    pos.castling = parts[2] if parts[2] != "-" else "-"
    pos.ep = -1 if parts[3] == "-" else sq_to_idx(parts[3])
    try:
        pos.halfmove = int(parts[4])
        pos.fullmove = int(parts[5])
    except Exception:
        pos.halfmove = 0
        pos.fullmove = 1
    return pos


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
        while on_board(s) and ray_ok(s - d, s, d):
            pc = b[s]
            if pc:
                if pc in (("B", "Q") if by_side == WHITE else ("b", "q")):
                    return True
                break
            s += d
    for d in ROOK_DELTAS:
        s = sq + d
        while on_board(s) and ray_ok(s - d, s, d):
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


def push(moves, fr, to, promo=None, flag=None):
    moves.append((fr, to, promo, flag))


def generate_pseudo(pos):
    b = pos.board
    side = pos.side
    moves = []
    for i, pc in enumerate(b):
        if not pc:
            continue
        if side == WHITE and not pc.isupper():
            continue
        if side == BLACK and not pc.islower():
            continue

        if pc in ("P", "p"):
            step = 8 if pc == "P" else -8
            start_rank = 1 if pc == "P" else 6
            promo_rank = 6 if pc == "P" else 1
            one = i + step
            if on_board(one) and b[one] is None:
                if (i >> 3) == promo_rank:
                    for pr in "QRBN":
                        push(moves, i, one, pr if pc == "P" else pr.lower())
                else:
                    push(moves, i, one)
                two = i + 2 * step
                if (i >> 3) == start_rank and on_board(two) and b[two] is None:
                    push(moves, i, two, flag="dbl")
            for capd in (step - 1, step + 1):
                to = i + capd
                if not on_board(to) or not pawn_cap_ok(i, to):
                    continue
                target = b[to]
                if target and target.isupper() != pc.isupper():
                    if (i >> 3) == promo_rank:
                        for pr in "QRBN":
                            push(moves, i, to, pr if pc == "P" else pr.lower())
                    else:
                        push(moves, i, to)
                elif to == pos.ep:
                    push(moves, i, to, flag="ep")
            continue

        if pc in ("N", "n"):
            for d in KNIGHT_DELTAS:
                to = i + d
                if on_board(to) and knight_ok(i, to):
                    target = b[to]
                    if not target or target.isupper() != pc.isupper():
                        push(moves, i, to)
            continue

        if pc in ("B", "b", "R", "r", "Q", "q"):
            deltas = BISHOP_DELTAS if pc.lower() == "b" else ROOK_DELTAS if pc.lower() == "r" else BISHOP_DELTAS + ROOK_DELTAS
            for d in deltas:
                to = i + d
                while on_board(to) and ray_ok(to - d, to, d):
                    target = b[to]
                    if not target:
                        push(moves, i, to)
                    else:
                        if target.isupper() != pc.isupper():
                            push(moves, i, to)
                        break
                    to += d
            continue

        for d in KING_DELTAS:
            to = i + d
            if on_board(to) and king_ok(i, to):
                target = b[to]
                if not target or target.isupper() != pc.isupper():
                    push(moves, i, to)
        if side == WHITE and i == 4:
            if "K" in pos.castling and b[5] is None and b[6] is None and not in_check(pos, WHITE) and not attacked_by(pos, 5, BLACK) and not attacked_by(pos, 6, BLACK):
                push(moves, 4, 6, flag="ck")
            if "Q" in pos.castling and b[3] is None and b[2] is None and b[1] is None and not in_check(pos, WHITE) and not attacked_by(pos, 3, BLACK) and not attacked_by(pos, 2, BLACK):
                push(moves, 4, 2, flag="cq")
        elif side == BLACK and i == 60:
            if "k" in pos.castling and b[61] is None and b[62] is None and not in_check(pos, BLACK) and not attacked_by(pos, 61, WHITE) and not attacked_by(pos, 62, WHITE):
                push(moves, 60, 62, flag="ck")
            if "q" in pos.castling and b[59] is None and b[58] is None and b[57] is None and not in_check(pos, BLACK) and not attacked_by(pos, 59, WHITE) and not attacked_by(pos, 58, WHITE):
                push(moves, 60, 58, flag="cq")
    return moves


def apply_move(pos, move):
    fr, to, promo, flag = move
    np = pos.clone()
    b = np.board
    pc = b[fr]
    captured = b[to]
    b[fr] = None
    np.ep = -1

    if pc in ("P", "p"):
        np.halfmove = 0
        if flag == "ep":
            cap_sq = to - 8 if pc == "P" else to + 8
            b[cap_sq] = None
        if flag == "dbl":
            np.ep = fr + (8 if pc == "P" else -8)
        if promo:
            pc = promo
    elif captured is not None:
        np.halfmove = 0
    else:
        np.halfmove += 1

    if pc == "K":
        np.king_sq[WHITE] = to
        np.castling = np.castling.replace("K", "").replace("Q", "")
        if flag == "ck":
            b[5], b[7] = b[7], None
        elif flag == "cq":
            b[3], b[0] = b[0], None
    elif pc == "k":
        np.king_sq[BLACK] = to
        np.castling = np.castling.replace("k", "").replace("q", "")
        if flag == "ck":
            b[61], b[63] = b[63], None
        elif flag == "cq":
            b[59], b[56] = b[56], None

    if fr == 0 or to == 0:
        np.castling = np.castling.replace("Q", "")
    if fr == 7 or to == 7:
        np.castling = np.castling.replace("K", "")
    if fr == 56 or to == 56:
        np.castling = np.castling.replace("q", "")
    if fr == 63 or to == 63:
        np.castling = np.castling.replace("k", "")

    b[to] = pc
    np.side ^= 1
    if np.side == WHITE:
        np.fullmove += 1
    if np.castling == "":
        np.castling = "-"
    return np


def legal_moves(pos):
    out = []
    for mv in generate_pseudo(pos):
        nxt = apply_move(pos, mv)
        if not in_check(nxt, pos.side):
            out.append(mv)
    return out


def move_to_uci(move):
    fr, to, promo, _ = move
    s = idx_to_sq(fr) + idx_to_sq(to)
    if promo:
        s += promo.lower()
    return s


def piece_square(pc, sq):
    tbl = PST[pc.upper()]
    return tbl[sq if pc.isupper() else 63 - sq]


def evaluate(pos):
    score = 0
    white_bishops = 0
    black_bishops = 0
    white_king = pos.king_sq[WHITE]
    black_king = pos.king_sq[BLACK]
    for sq, pc in enumerate(pos.board):
        if not pc:
            continue
        val = PIECE_VALUES[pc.upper()] + piece_square(pc, sq)
        score += val if pc.isupper() else -val
        if pc == "B":
            white_bishops += 1
        elif pc == "b":
            black_bishops += 1

    if white_bishops >= 2:
        score += 25
    if black_bishops >= 2:
        score -= 25

    for side, king_sq, sign in ((WHITE, white_king, 1), (BLACK, black_king, -1)):
        file = king_sq & 7
        rank = king_sq >> 3
        shield = 0
        if side == WHITE:
            ranks = (rank + 1,)
            pawn = "P"
        else:
            ranks = (rank - 1,)
            pawn = "p"
        for f in (file - 1, file, file + 1):
            if 0 <= f < 8:
                for r in ranks:
                    if 0 <= r < 8 and pos.board[r * 8 + f] == pawn:
                        shield += 1
        score += sign * shield * 8

    if pos.side == WHITE:
        return score
    return -score


def move_order(pos, move):
    fr, to, promo, flag = move
    b = pos.board
    pc = b[fr]
    target = b[to]
    score = 0
    if flag == "ep":
        score += 1050
    if target:
        score += 10 * PIECE_VALUES[target.upper()] - PIECE_VALUES[pc.upper()] + 500
    if promo:
        score += PIECE_VALUES[promo.upper()] + 1000
    if pc and pc.upper() == "K" and abs(to - fr) == 2:
        score -= 20
    return score


TIME_UP = False


def qsearch(pos, alpha, beta, end_time):
    global TIME_UP
    if TIME_UP or time.perf_counter() >= end_time:
        TIME_UP = True
        return evaluate(pos)
    stand = evaluate(pos)
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    moves = legal_moves(pos)
    noisy = []
    for mv in moves:
        fr, to, promo, flag = mv
        if promo or flag == "ep" or pos.board[to] is not None:
            noisy.append(mv)
    noisy.sort(key=lambda m: move_order(pos, m), reverse=True)
    for mv in noisy:
        nxt = apply_move(pos, mv)
        sc = -qsearch(nxt, -beta, -alpha, end_time)
        if TIME_UP:
            return alpha
        if sc >= beta:
            return beta
        if sc > alpha:
            alpha = sc
    return alpha


def search(pos, depth, alpha, beta, end_time):
    global TIME_UP
    if TIME_UP or time.perf_counter() >= end_time:
        TIME_UP = True
        return evaluate(pos)
    if depth <= 0:
        return qsearch(pos, alpha, beta, end_time)
    moves = legal_moves(pos)
    if not moves:
        if in_check(pos, pos.side):
            return -100000 + (4 - depth)
        return 0
    moves.sort(key=lambda m: move_order(pos, m), reverse=True)
    best = -10**9
    for mv in moves:
        nxt = apply_move(pos, mv)
        sc = -search(nxt, depth - 1, -beta, -alpha, end_time)
        if TIME_UP:
            return best if best > -10**8 else sc
        if sc > best:
            best = sc
        if sc > alpha:
            alpha = sc
        if alpha >= beta:
            break
    return best


def choose_move(pos, movetime_ms):
    moves = legal_moves(pos)
    if not moves:
        return "0000"
    if len(moves) == 1:
        return move_to_uci(moves[0])
    start = time.perf_counter()
    end_time = start + max(0.002, movetime_ms / 1000.0 * 0.95)
    ordered = sorted(moves, key=lambda m: move_order(pos, m), reverse=True)
    best = ordered[0]
    max_depth = 4 if movetime_ms >= 35 else 3
    for depth in range(1, max_depth + 1):
        global TIME_UP
        TIME_UP = False
        alpha = -10**9
        beta = 10**9
        cur_best = best
        cur_score = -10**9
        for mv in ordered:
            if time.perf_counter() >= end_time:
                TIME_UP = True
                break
            sc = -search(apply_move(pos, mv), depth - 1, -beta, -alpha, end_time)
            if TIME_UP:
                break
            if sc > cur_score:
                cur_score = sc
                cur_best = mv
            if sc > alpha:
                alpha = sc
        if not TIME_UP:
            best = cur_best
    return move_to_uci(best)


def parse_moves(move_tokens, pos):
    i = 0
    while i < len(move_tokens):
        mv = move_tokens[i]
        if len(mv) < 4:
            break
        try:
            fr = sq_to_idx(mv[:2])
            to = sq_to_idx(mv[2:4])
        except Exception:
            break
        promo = mv[4].upper() if len(mv) > 4 else None
        found = None
        for legal in legal_moves(pos):
            if legal[0] == fr and legal[1] == to:
                if (promo is None and legal[2] is None) or (promo is not None and legal[2] and legal[2].upper() == promo):
                    found = legal
                    break
        if found is None:
            break
        pos = apply_move(pos, found)
        i += 1
    return pos


def parse_position(cmd):
    parts = cmd.split()
    pos = parse_fen(STARTPOS)
    if len(parts) < 2:
        return pos
    if parts[1] == "startpos":
        if "moves" in parts:
            pos = parse_moves(parts[parts.index("moves") + 1 :], pos)
        return pos
    if parts[1] == "fen":
        if "moves" in parts:
            idx = parts.index("moves")
            fen = " ".join(parts[2:idx])
            pos = parse_fen(fen)
            pos = parse_moves(parts[idx + 1 :], pos)
        else:
            pos = parse_fen(" ".join(parts[2:8]))
        return pos
    return pos


def main():
    pos = parse_fen(STARTPOS)
    for raw in sys.stdin:
        cmd = raw.strip()
        if not cmd:
            continue
        if cmd == "uci":
            sys.stdout.write("id name MinimalPythonEngine\n")
            sys.stdout.write("id author Codex\n")
            sys.stdout.write("uciok\n")
            sys.stdout.flush()
        elif cmd == "isready":
            sys.stdout.write("readyok\n")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            pos = parse_fen(STARTPOS)
        elif cmd.startswith("position "):
            pos = parse_position(cmd)
        elif cmd.startswith("go "):
            parts = cmd.split()
            movetime = 20
            if "movetime" in parts:
                try:
                    movetime = int(parts[parts.index("movetime") + 1])
                except Exception:
                    movetime = 20
            bm = choose_move(pos, movetime)
            sys.stdout.write(f"bestmove {bm}\n")
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

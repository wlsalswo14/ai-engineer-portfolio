#!/usr/bin/env python3
import sys
import time

FILES = "abcdefgh"
RANKS = "12345678"

WHITE, BLACK = 0, 1
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = "PNBRQK"
PIECE_VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}


def sq_name(i):
    return FILES[i % 8] + RANKS[i // 8]


def parse_sq(s):
    if len(s) != 2 or s[0] not in FILES or s[1] not in RANKS:
        return None
    return (int(s[1]) - 1) * 8 + FILES.index(s[0])


class Move:
    __slots__ = ("from_sq", "to_sq", "promo", "ep", "castle")

    def __init__(self, from_sq, to_sq, promo=None, ep=False, castle=False):
        self.from_sq = from_sq
        self.to_sq = to_sq
        self.promo = promo
        self.ep = ep
        self.castle = castle

    def uci(self):
        s = sq_name(self.from_sq) + sq_name(self.to_sq)
        return s + self.promo.lower() if self.promo else s


class Position:
    def __init__(self):
        self.board = [None] * 64
        self.side = WHITE
        self.castling = "-"
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = [None, None]
        self.history = []

    def set_startpos(self):
        self.set_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            return
        board_part, stm, castling, ep = parts[:4]
        hm = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        fm = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
        self.board = [None] * 64
        self.king_sq = [None, None]
        rows = board_part.split("/")
        if len(rows) != 8:
            return
        for r, row in enumerate(rows[::-1]):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif ch.isalpha() and f < 8:
                    sq = r * 8 + f
                    self.board[sq] = ch
                    if ch == "K":
                        self.king_sq[WHITE] = sq
                    elif ch == "k":
                        self.king_sq[BLACK] = sq
                    f += 1
                else:
                    return
        self.side = WHITE if stm == "w" else BLACK
        self.castling = castling if castling != "-" else "-"
        self.ep = parse_sq(ep) if ep != "-" else None
        self.halfmove = hm
        self.fullmove = fm

    def copy_state(self):
        return (self.board[:], self.side, self.castling, self.ep, self.halfmove, self.fullmove, self.king_sq[:])

    def restore_state(self, st):
        self.board, self.side, self.castling, self.ep, self.halfmove, self.fullmove, self.king_sq = st

    def piece_at(self, sq):
        return self.board[sq]

    def enemy(self):
        return BLACK if self.side == WHITE else WHITE

    def is_white_piece(self, p):
        return p is not None and p.isupper()

    def attacks_square(self, sq, by_side):
        b = self.board
        rank, file = divmod(sq, 8)
        if by_side == WHITE:
            for df in (-1, 1):
                r, f = rank - 1, file + df
                if 0 <= r < 8 and 0 <= f < 8 and b[r * 8 + f] == "P":
                    return True
        else:
            for df in (-1, 1):
                r, f = rank + 1, file + df
                if 0 <= r < 8 and 0 <= f < 8 and b[r * 8 + f] == "p":
                    return True
        knight_offsets = [(1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)]
        target = "N" if by_side == WHITE else "n"
        for dr, df in knight_offsets:
            r, f = rank + dr, file + df
            if 0 <= r < 8 and 0 <= f < 8 and b[r * 8 + f] == target:
                return True
        for dr, df, sliders in ((1, 1, "BQ"), (1, -1, "BQ"), (-1, 1, "BQ"), (-1, -1, "BQ")):
            r, f = rank + dr, file + df
            while 0 <= r < 8 and 0 <= f < 8:
                p = b[r * 8 + f]
                if p:
                    if p.isupper() == (by_side == WHITE) and p.upper() in sliders:
                        return True
                    break
                r += dr
                f += df
        for dr, df, sliders in ((1, 0, "RQ"), (-1, 0, "RQ"), (0, 1, "RQ"), (0, -1, "RQ")):
            r, f = rank + dr, file + df
            while 0 <= r < 8 and 0 <= f < 8:
                p = b[r * 8 + f]
                if p:
                    if p.isupper() == (by_side == WHITE) and p.upper() in sliders:
                        return True
                    break
                r += dr
                f += df
        target = "K" if by_side == WHITE else "k"
        for dr in (-1, 0, 1):
            for df in (-1, 0, 1):
                if dr == df == 0:
                    continue
                r, f = rank + dr, file + df
                if 0 <= r < 8 and 0 <= f < 8 and b[r * 8 + f] == target:
                    return True
        return False

    def in_check(self, side):
        ks = self.king_sq[side]
        if ks is None:
            return False
        return self.attacks_square(ks, BLACK if side == WHITE else WHITE)

    def gen_pseudo(self):
        b = self.board
        side = self.side
        us_white = side == WHITE
        for sq, p in enumerate(b):
            if not p or (p.isupper() != us_white):
                continue
            r, f = divmod(sq, 8)
            if p.upper() == "P":
                step = 8 if us_white else -8
                start_rank = 1 if us_white else 6
                promo_rank = 7 if us_white else 0
                one = sq + step
                if 0 <= one < 64 and b[one] is None:
                    if one // 8 == promo_rank:
                        for pr in "qrbn":
                            yield Move(sq, one, pr.upper())
                    else:
                        yield Move(sq, one)
                    two = sq + step * 2
                    if r == start_rank and b[two] is None:
                        yield Move(sq, two)
                for df in (-1, 1):
                    nf = f + df
                    nr = r + (1 if us_white else -1)
                    if 0 <= nf < 8 and 0 <= nr < 8:
                        to = nr * 8 + nf
                        tp = b[to]
                        if tp and (tp.isupper() != us_white):
                            if nr == promo_rank:
                                for pr in "qrbn":
                                    yield Move(sq, to, pr.upper())
                            else:
                                yield Move(sq, to)
                        elif self.ep == to:
                            yield Move(sq, to, ep=True)
            elif p.upper() == "N":
                for dr, df in ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)):
                    nr, nf = r + dr, f + df
                    if 0 <= nr < 8 and 0 <= nf < 8:
                        to = nr * 8 + nf
                        tp = b[to]
                        if not tp or tp.isupper() != us_white:
                            yield Move(sq, to)
            elif p.upper() in ("B", "R", "Q"):
                dirs = []
                if p.upper() in ("B", "Q"):
                    dirs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
                if p.upper() in ("R", "Q"):
                    dirs += [(1, 0), (-1, 0), (0, 1), (0, -1)]
                for dr, df in dirs:
                    nr, nf = r + dr, f + df
                    while 0 <= nr < 8 and 0 <= nf < 8:
                        to = nr * 8 + nf
                        tp = b[to]
                        if not tp:
                            yield Move(sq, to)
                        else:
                            if tp.isupper() != us_white:
                                yield Move(sq, to)
                            break
                        nr += dr
                        nf += df
            else:  # king
                for dr in (-1, 0, 1):
                    for df in (-1, 0, 1):
                        if dr == df == 0:
                            continue
                        nr, nf = r + dr, f + df
                        if 0 <= nr < 8 and 0 <= nf < 8:
                            to = nr * 8 + nf
                            tp = b[to]
                            if not tp or tp.isupper() != us_white:
                                yield Move(sq, to)
                if us_white and sq == 4:
                    if "K" in self.castling and b[5] is None and b[6] is None and not self.in_check(WHITE) and not self.attacks_square(5, BLACK) and not self.attacks_square(6, BLACK):
                        yield Move(4, 6, castle=True)
                    if "Q" in self.castling and b[3] is None and b[2] is None and b[1] is None and not self.in_check(WHITE) and not self.attacks_square(3, BLACK) and not self.attacks_square(2, BLACK):
                        yield Move(4, 2, castle=True)
                elif (not us_white) and sq == 60:
                    if "k" in self.castling and b[61] is None and b[62] is None and not self.in_check(BLACK) and not self.attacks_square(61, WHITE) and not self.attacks_square(62, WHITE):
                        yield Move(60, 62, castle=True)
                    if "q" in self.castling and b[59] is None and b[58] is None and b[57] is None and not self.in_check(BLACK) and not self.attacks_square(59, WHITE) and not self.attacks_square(58, WHITE):
                        yield Move(60, 58, castle=True)

    def make(self, mv):
        st = self.copy_state()
        b = self.board
        p = b[mv.from_sq]
        captured = b[mv.to_sq]
        self.history.append(st)
        self.ep = None
        self.halfmove += 1
        if p is None:
            return
        if p.upper() == "P":
            self.halfmove = 0
        if captured:
            self.halfmove = 0
        b[mv.from_sq] = None
        if mv.ep:
            cap_sq = mv.to_sq - 8 if self.side == WHITE else mv.to_sq + 8
            b[cap_sq] = None
            self.halfmove = 0
        if mv.castle and p.upper() == "K":
            if mv.to_sq == 6:
                b[5] = b[7]
                b[7] = None
            elif mv.to_sq == 2:
                b[3] = b[0]
                b[0] = None
            elif mv.to_sq == 62:
                b[61] = b[63]
                b[63] = None
            elif mv.to_sq == 58:
                b[59] = b[56]
                b[56] = None
        if mv.promo:
            b[mv.to_sq] = mv.promo if self.side == WHITE else mv.promo.lower()
            self.halfmove = 0
        else:
            b[mv.to_sq] = p
        if p == "K":
            self.king_sq[WHITE] = mv.to_sq
            self.castling = self.castling.replace("K", "").replace("Q", "")
        elif p == "k":
            self.king_sq[BLACK] = mv.to_sq
            self.castling = self.castling.replace("k", "").replace("q", "")
        if p == "R":
            if mv.from_sq == 0:
                self.castling = self.castling.replace("Q", "")
            elif mv.from_sq == 7:
                self.castling = self.castling.replace("K", "")
        elif p == "r":
            if mv.from_sq == 56:
                self.castling = self.castling.replace("q", "")
            elif mv.from_sq == 63:
                self.castling = self.castling.replace("k", "")
        if captured == "R":
            if mv.to_sq == 0:
                self.castling = self.castling.replace("Q", "")
            elif mv.to_sq == 7:
                self.castling = self.castling.replace("K", "")
        elif captured == "r":
            if mv.to_sq == 56:
                self.castling = self.castling.replace("q", "")
            elif mv.to_sq == 63:
                self.castling = self.castling.replace("k", "")
        if p.upper() == "P" and abs(mv.to_sq - mv.from_sq) == 16:
            self.ep = (mv.from_sq + mv.to_sq) // 2
        self.side = BLACK if self.side == WHITE else WHITE
        if self.side == WHITE:
            self.fullmove += 1
        return st

    def undo(self):
        if self.history:
            self.restore_state(self.history.pop())

    def legal_moves(self):
        for mv in self.gen_pseudo():
            st = self.make(mv)
            if st is None:
                self.undo()
                continue
            moved_side = BLACK if self.side == WHITE else WHITE
            ok = not self.in_check(moved_side)
            self.undo()
            if ok:
                yield mv


def evaluate(pos):
    score = 0
    for p in pos.board:
        if not p:
            continue
        v = PIECE_VALUE[p.upper()]
        score += v if p.isupper() else -v
    if pos.in_check(pos.side):
        score += -20 if pos.side == WHITE else 20
    return score if pos.side == WHITE else -score


def move_order_key(pos, mv):
    b = pos.board
    target = b[mv.to_sq]
    score = 0
    if mv.promo:
        score += 800 + PIECE_VALUE[mv.promo]
    if mv.castle:
        score += 40
    if mv.ep:
        score += 100
    if target:
        score += 10 * PIECE_VALUE[target.upper()] - PIECE_VALUE[b[mv.from_sq].upper()]
    return -score


def negamax(pos, depth, alpha, beta, start, limit):
    if time.time() >= limit:
        raise TimeoutError
    moves = list(pos.legal_moves())
    if depth == 0 or not moves:
        if not moves:
            return -100000 if pos.in_check(pos.side) else 0, None
        return evaluate(pos), None
    moves.sort(key=lambda m: move_order_key(pos, m))
    best = None
    best_score = -10**9
    for mv in moves:
        st = pos.make(mv)
        if st is None:
            pos.undo()
            continue
        try:
            score, _ = negamax(pos, depth - 1, -beta, -alpha, start, limit)
            score = -score
        finally:
            pos.undo()
        if score > best_score:
            best_score = score
            best = mv
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
    return best_score, best


def pick_move(pos, movetime_ms):
    legal = list(pos.legal_moves())
    if not legal:
        return "0000"
    if len(legal) == 1:
        return legal[0].uci()
    legal.sort(key=lambda m: move_order_key(pos, m))
    return legal[0].uci()


def apply_moves(pos, moves):
    for m in moves:
        if len(m) < 4:
            continue
        fs = parse_sq(m[:2])
        ts = parse_sq(m[2:4])
        if fs is None or ts is None:
            continue
        promo = m[4].upper() if len(m) > 4 else None
        chosen = None
        for mv in pos.legal_moves():
            if mv.from_sq == fs and mv.to_sq == ts and ((mv.promo or None) == promo or (mv.promo and mv.promo.lower() == (promo or "").lower())):
                chosen = mv
                break
        if chosen:
            pos.make(chosen)


def main():
    pos = Position()
    pos.set_startpos()
    for raw in sys.stdin:
        cmd = raw.strip()
        if not cmd:
            continue
        if cmd == "uci":
            print("id name SimplePythonEngine")
            print("id author openai")
            print("uciok")
            sys.stdout.flush()
        elif cmd == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            pos.set_startpos()
        elif cmd.startswith("position "):
            parts = cmd.split()
            if len(parts) >= 2:
                if parts[1] == "startpos":
                    pos.set_startpos()
                    if "moves" in parts:
                        apply_moves(pos, parts[parts.index("moves") + 1 :])
                elif parts[1] == "fen":
                    idx = cmd.find(" fen ")
                    rest = cmd[idx + 5 :] if idx >= 0 else cmd[8:]
                    if " moves " in rest:
                        fen, move_part = rest.split(" moves ", 1)
                        pos.set_fen(fen)
                        apply_moves(pos, move_part.split())
                    else:
                        pos.set_fen(rest)
        elif cmd.startswith("go "):
            parts = cmd.split()
            movetime = 20
            if "movetime" in parts:
                try:
                    movetime = int(parts[parts.index("movetime") + 1])
                except Exception:
                    pass
            print("bestmove " + pick_move(pos, movetime))
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

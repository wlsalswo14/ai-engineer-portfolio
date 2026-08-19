#!/usr/bin/env python3
import sys
import time

FILES = "abcdefgh"
RANKS = "12345678"
WHITE, BLACK = 0, 1
PIECE_VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
KNIGHT_DIRS = ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1))
KING_DIRS = ((1, 1), (1, 0), (1, -1), (0, 1), (0, -1), (-1, 1), (-1, 0), (-1, -1))


def sq_name(sq):
    return FILES[sq % 8] + RANKS[sq // 8]


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
        self.set_startpos()

    def set_startpos(self):
        self.set_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def _clear(self):
        self.board = [None] * 64
        self.side = WHITE
        self.castling = "-"
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = [None, None]
        self.history = []

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            self._clear()
            return False
        board_part, stm, castling, ep = parts[:4]
        try:
            hm = int(parts[4]) if len(parts) > 4 else 0
            fm = int(parts[5]) if len(parts) > 5 else 1
        except Exception:
            hm, fm = 0, 1
        rows = board_part.split("/")
        if len(rows) != 8:
            self._clear()
            return False
        board = [None] * 64
        king_sq = [None, None]
        for r, row in enumerate(rows[::-1]):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif ch.isalpha() and f < 8:
                    sq = r * 8 + f
                    board[sq] = ch
                    if ch == "K":
                        king_sq[WHITE] = sq
                    elif ch == "k":
                        king_sq[BLACK] = sq
                    f += 1
                else:
                    self._clear()
                    return False
            if f != 8:
                self._clear()
                return False
        self.board = board
        self.king_sq = king_sq
        self.side = WHITE if stm == "w" else BLACK
        self.castling = castling if castling != "-" else "-"
        self.ep = parse_sq(ep) if ep != "-" else None
        self.halfmove = hm if hm >= 0 else 0
        self.fullmove = fm if fm >= 1 else 1
        self.history = []
        return True

    def copy_state(self):
        return (self.board[:], self.side, self.castling, self.ep, self.halfmove, self.fullmove, self.king_sq[:])

    def restore_state(self, st):
        self.board, self.side, self.castling, self.ep, self.halfmove, self.fullmove, self.king_sq = st

    def in_bounds(self, r, f):
        return 0 <= r < 8 and 0 <= f < 8

    def attacks_square(self, sq, by_side):
        b = self.board
        r, f = divmod(sq, 8)
        if by_side == WHITE:
            rr = r - 1
            if rr >= 0:
                if f > 0 and b[rr * 8 + f - 1] == "P":
                    return True
                if f < 7 and b[rr * 8 + f + 1] == "P":
                    return True
        else:
            rr = r + 1
            if rr < 8:
                if f > 0 and b[rr * 8 + f - 1] == "p":
                    return True
                if f < 7 and b[rr * 8 + f + 1] == "p":
                    return True
        target = "N" if by_side == WHITE else "n"
        for dr, df in KNIGHT_DIRS:
            rr, ff = r + dr, f + df
            if self.in_bounds(rr, ff) and b[rr * 8 + ff] == target:
                return True
        bishop_like = "BQ" if by_side == WHITE else "bq"
        rook_like = "RQ" if by_side == WHITE else "rq"
        for dr, df in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            rr, ff = r + dr, f + df
            while self.in_bounds(rr, ff):
                p = b[rr * 8 + ff]
                if p:
                    if p in bishop_like:
                        return True
                    break
                rr += dr
                ff += df
        for dr, df in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, ff = r + dr, f + df
            while self.in_bounds(rr, ff):
                p = b[rr * 8 + ff]
                if p:
                    if p in rook_like:
                        return True
                    break
                rr += dr
                ff += df
        target = "K" if by_side == WHITE else "k"
        for dr, df in KING_DIRS:
            rr, ff = r + dr, f + df
            if self.in_bounds(rr, ff) and b[rr * 8 + ff] == target:
                return True
        return False

    def in_check(self, side):
        ks = self.king_sq[side]
        return ks is not None and self.attacks_square(ks, BLACK if side == WHITE else WHITE)

    def gen_pseudo(self):
        b = self.board
        us_white = self.side == WHITE
        for sq, p in enumerate(b):
            if not p or (p.isupper() != us_white):
                continue
            r, f = divmod(sq, 8)
            kind = p.upper()
            if kind == "P":
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
                    if r == start_rank and 0 <= two < 64 and b[two] is None:
                        yield Move(sq, two)
                nr = r + (1 if us_white else -1)
                if 0 <= nr < 8:
                    for df in (-1, 1):
                        nf = f + df
                        if 0 <= nf < 8:
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
            elif kind == "N":
                for dr, df in KNIGHT_DIRS:
                    nr, nf = r + dr, f + df
                    if self.in_bounds(nr, nf):
                        to = nr * 8 + nf
                        tp = b[to]
                        if not tp or tp.isupper() != us_white:
                            yield Move(sq, to)
            elif kind in ("B", "R", "Q"):
                dirs = []
                if kind in ("B", "Q"):
                    dirs.extend(((1, 1), (1, -1), (-1, 1), (-1, -1)))
                if kind in ("R", "Q"):
                    dirs.extend(((1, 0), (-1, 0), (0, 1), (0, -1)))
                for dr, df in dirs:
                    nr, nf = r + dr, f + df
                    while self.in_bounds(nr, nf):
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
            else:
                for dr, df in KING_DIRS:
                    nr, nf = r + dr, f + df
                    if self.in_bounds(nr, nf):
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
        self.history.append(st)
        b = self.board
        p = b[mv.from_sq]
        if p is None:
            return None
        captured = b[mv.to_sq]
        self.ep = None
        self.halfmove += 1
        if p.upper() == "P" or captured:
            self.halfmove = 0
        b[mv.from_sq] = None
        if mv.ep:
            cap_sq = mv.to_sq - 8 if self.side == WHITE else mv.to_sq + 8
            if 0 <= cap_sq < 64:
                b[cap_sq] = None
            self.halfmove = 0
        if mv.castle and p.upper() == "K":
            if mv.to_sq == 6:
                b[5], b[7] = b[7], None
            elif mv.to_sq == 2:
                b[3], b[0] = b[0], None
            elif mv.to_sq == 62:
                b[61], b[63] = b[63], None
            elif mv.to_sq == 58:
                b[59], b[56] = b[56], None
        placed = p
        if mv.promo:
            placed = mv.promo if self.side == WHITE else mv.promo.lower()
            self.halfmove = 0
        b[mv.to_sq] = placed
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
        if p:
            score += PIECE_VALUE[p.upper()] if p.isupper() else -PIECE_VALUE[p.upper()]
    # Mild king-safety pressure.
    if pos.in_check(pos.side):
        score += -25 if pos.side == WHITE else 25
    return score if pos.side == WHITE else -score


def move_order_key(pos, mv):
    b = pos.board
    target = b[mv.to_sq]
    attacker = b[mv.from_sq]
    score = 0
    if mv.promo:
        score += 800 + PIECE_VALUE[mv.promo]
    if mv.castle:
        score += 40
    if mv.ep:
        score += 100
    if target:
        score += 10 * PIECE_VALUE[target.upper()] - PIECE_VALUE[attacker.upper()]
    return -score


def negamax(pos, depth, alpha, beta, deadline):
    if time.time() >= deadline:
        raise TimeoutError
    moves = list(pos.legal_moves())
    if depth == 0 or not moves:
        if not moves:
            return (-100000 if pos.in_check(pos.side) else 0), None
        return evaluate(pos), None
    moves.sort(key=lambda m: move_order_key(pos, m))
    best_move = moves[0]
    best_score = -10**9
    for mv in moves:
        st = pos.make(mv)
        try:
            score, _ = negamax(pos, depth - 1, -beta, -alpha, deadline)
            score = -score
        finally:
            pos.undo()
        if score > best_score:
            best_score = score
            best_move = mv
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
        if time.time() >= deadline:
            raise TimeoutError
    return best_score, best_move


def pick_move(pos, movetime_ms):
    legal = list(pos.legal_moves())
    if not legal:
        return "0000"
    legal.sort(key=lambda m: move_order_key(pos, m))
    return legal[0].uci()


def apply_moves(pos, moves):
    for token in moves:
        if len(token) < 4:
            continue
        fs = parse_sq(token[:2])
        ts = parse_sq(token[2:4])
        if fs is None or ts is None:
            continue
        promo = token[4].upper() if len(token) > 4 else None
        chosen = None
        for mv in pos.legal_moves():
            if mv.from_sq == fs and mv.to_sq == ts:
                if (mv.promo or None) == promo or (mv.promo and mv.promo.lower() == (promo or "").lower()):
                    chosen = mv
                    break
        if chosen is None:
            continue
        pos.make(chosen)


def parse_position(pos, cmd):
    parts = cmd.split()
    if len(parts) < 2:
        return
    if parts[1] == "startpos":
        pos.set_startpos()
        if "moves" in parts:
            apply_moves(pos, parts[parts.index("moves") + 1 :])
        return
    if parts[1] == "fen":
        fen_and_moves = cmd[cmd.find(" fen ") + 5 :] if " fen " in cmd else cmd[8:]
        if " moves " in fen_and_moves:
            fen, move_part = fen_and_moves.split(" moves ", 1)
            pos.set_fen(fen)
            apply_moves(pos, move_part.split())
        else:
            pos.set_fen(fen_and_moves)


def main():
    pos = Position()
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
            parse_position(pos, cmd)
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

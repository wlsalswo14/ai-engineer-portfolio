import sys
import time

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
VAL = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
INF = 10**9
MATE = 100000

N_DIRS = (-17, -15, -10, -6, 6, 10, 15, 17)
B_DIRS = (-9, -7, 7, 9)
R_DIRS = (-8, -1, 1, 8)
Q_DIRS = B_DIRS + R_DIRS
K_DIRS = Q_DIRS
FILES = "abcdefgh"

PAWN_PST = [
    0, 0, 0, 0, 0, 0, 0, 0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
    5, 5, 10, 25, 25, 10, 5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, -5, -10, 0, 0, -10, -5, 5,
    5, 10, 10, -20, -20, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0,
]
KNIGHT_PST = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]
BISHOP_PST = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]
ROOK_PST = [
    0, 0, 0, 5, 5, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0,
]
QUEEN_PST = [
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -10, 5, 5, 5, 5, 5, 0, -10,
    0, 0, 5, 5, 5, 5, 0, -5,
    -5, 0, 5, 5, 5, 5, 0, -5,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20,
]
KING_PST = [
    20, 30, 10, 0, 0, 10, 30, 20,
    20, 20, 0, 0, 0, 0, 20, 20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
]
PST = {"P": PAWN_PST, "N": KNIGHT_PST, "B": BISHOP_PST, "R": ROOK_PST, "Q": QUEEN_PST, "K": KING_PST}


def color(p):
    return 1 if p.isupper() else -1


def rc(sq):
    return divmod(sq, 8)


def on_board(sq):
    return 0 <= sq < 64


def step_ok(a, b, d):
    if not on_board(b):
        return False
    ar, af = rc(a)
    br, bf = rc(b)
    if d in (-1, 1):
        return ar == br
    if d in (-9, 7):
        return br == ar - 1 and bf == af - 1
    if d in (-7, 9):
        return br == ar + (1 if d == 9 else -1) and bf == af + 1
    return abs(br - ar) <= 2 and abs(bf - af) <= 2


def sq_name(sq):
    r, f = rc(sq)
    return FILES[f] + str(8 - r)


def parse_sq(s):
    if len(s) != 2 or s[0] not in FILES or s[1] not in "12345678":
        return -1
    return (8 - int(s[1])) * 8 + FILES.index(s[0])


class Position:
    def __init__(self):
        self.board = ["."] * 64
        self.side = 1
        self.castle = ""
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.set_fen(START_FEN)

    def clone(self):
        p = Position.__new__(Position)
        p.board = self.board[:]
        p.side = self.side
        p.castle = self.castle
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        return p

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            parts = START_FEN.split()
        b = []
        try:
            for row in parts[0].split("/"):
                for ch in row:
                    if ch.isdigit():
                        b.extend(["."] * int(ch))
                    else:
                        b.append(ch)
            if len(b) != 64:
                raise ValueError
            self.board = b
            self.side = 1 if parts[1] == "w" else -1
            self.castle = "" if parts[2] == "-" else parts[2]
            self.ep = -1 if parts[3] == "-" else parse_sq(parts[3])
            self.halfmove = int(parts[4]) if len(parts) > 4 else 0
            self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        except Exception:
            self.set_fen(START_FEN)

    def king_sq(self, side):
        k = "K" if side == 1 else "k"
        try:
            return self.board.index(k)
        except ValueError:
            return -1

    def attacked(self, sq, by_side):
        pawn_dirs = (7, 9) if by_side == 1 else (-7, -9)
        pawn = "P" if by_side == 1 else "p"
        for d in pawn_dirs:
            s = sq + d
            if on_board(s) and step_ok(s, sq, -d) and self.board[s] == pawn:
                return True
        knight = "N" if by_side == 1 else "n"
        for d in N_DIRS:
            s = sq + d
            if on_board(s) and step_ok(sq, s, d) and self.board[s] == knight:
                return True
        bishop = ("B", "Q") if by_side == 1 else ("b", "q")
        for d in B_DIRS:
            s = sq + d
            while on_board(s) and step_ok(s - d, s, d):
                p = self.board[s]
                if p != ".":
                    if p in bishop:
                        return True
                    break
                s += d
        rook = ("R", "Q") if by_side == 1 else ("r", "q")
        for d in R_DIRS:
            s = sq + d
            while on_board(s) and step_ok(s - d, s, d):
                p = self.board[s]
                if p != ".":
                    if p in rook:
                        return True
                    break
                s += d
        king = "K" if by_side == 1 else "k"
        for d in K_DIRS:
            s = sq + d
            if on_board(s) and step_ok(sq, s, d) and self.board[s] == king:
                return True
        return False

    def in_check(self, side=None):
        side = self.side if side is None else side
        k = self.king_sq(side)
        return k < 0 or self.attacked(k, -side)

    def pseudo_moves(self, captures_only=False):
        moves = []
        us = self.side
        for i, p in enumerate(self.board):
            if p == "." or color(p) != us:
                continue
            up = p.upper()
            if up == "P":
                self._pawn_moves(i, p, moves, captures_only)
            elif up == "N":
                self._jump_moves(i, p, N_DIRS, moves, captures_only)
            elif up == "B":
                self._slide_moves(i, p, B_DIRS, moves, captures_only)
            elif up == "R":
                self._slide_moves(i, p, R_DIRS, moves, captures_only)
            elif up == "Q":
                self._slide_moves(i, p, Q_DIRS, moves, captures_only)
            elif up == "K":
                self._jump_moves(i, p, K_DIRS, moves, captures_only)
                if not captures_only:
                    self._castle_moves(i, p, moves)
        return moves

    def _add(self, moves, fr, to, promo=""):
        moves.append((fr, to, promo))

    def _pawn_moves(self, i, p, moves, captures_only):
        us = color(p)
        r, f = rc(i)
        forward = -8 if us == 1 else 8
        start_rank = 6 if us == 1 else 1
        promo_rank = 0 if us == 1 else 7
        one = i + forward
        if not captures_only and on_board(one) and self.board[one] == ".":
            if rc(one)[0] == promo_rank:
                for pr in "qrbn":
                    self._add(moves, i, one, pr)
            else:
                self._add(moves, i, one)
                two = one + forward
                if r == start_rank and self.board[two] == ".":
                    self._add(moves, i, two)
        for df in (-1, 1):
            if 0 <= f + df < 8:
                to = i + forward + df
                if on_board(to):
                    target = self.board[to]
                    if target != "." and color(target) == -us:
                        if rc(to)[0] == promo_rank:
                            for pr in "qrbn":
                                self._add(moves, i, to, pr)
                        else:
                            self._add(moves, i, to)
                    elif to == self.ep:
                        self._add(moves, i, to)

    def _jump_moves(self, i, p, dirs, moves, captures_only):
        us = color(p)
        for d in dirs:
            to = i + d
            if not on_board(to) or not step_ok(i, to, d):
                continue
            q = self.board[to]
            if q == ".":
                if not captures_only:
                    self._add(moves, i, to)
            elif color(q) == -us:
                self._add(moves, i, to)

    def _slide_moves(self, i, p, dirs, moves, captures_only):
        us = color(p)
        for d in dirs:
            to = i + d
            while on_board(to) and step_ok(to - d, to, d):
                q = self.board[to]
                if q == ".":
                    if not captures_only:
                        self._add(moves, i, to)
                else:
                    if color(q) == -us:
                        self._add(moves, i, to)
                    break
                to += d

    def _castle_moves(self, i, p, moves):
        if self.in_check(self.side):
            return
        if p == "K" and i == 60:
            if "K" in self.castle and self.board[61] == self.board[62] == ".":
                if not self.attacked(61, -1) and not self.attacked(62, -1) and self.board[63] == "R":
                    self._add(moves, 60, 62)
            if "Q" in self.castle and self.board[59] == self.board[58] == self.board[57] == ".":
                if not self.attacked(59, -1) and not self.attacked(58, -1) and self.board[56] == "R":
                    self._add(moves, 60, 58)
        elif p == "k" and i == 4:
            if "k" in self.castle and self.board[5] == self.board[6] == ".":
                if not self.attacked(5, 1) and not self.attacked(6, 1) and self.board[7] == "r":
                    self._add(moves, 4, 6)
            if "q" in self.castle and self.board[3] == self.board[2] == self.board[1] == ".":
                if not self.attacked(3, 1) and not self.attacked(2, 1) and self.board[0] == "r":
                    self._add(moves, 4, 2)

    def legal_moves(self, captures_only=False):
        out = []
        for m in self.pseudo_moves(captures_only):
            p = self.make(m)
            if not p.in_check(-p.side):
                out.append(m)
        return out

    def make(self, m):
        fr, to, promo = m
        p = self.clone()
        piece = p.board[fr]
        target = p.board[to]
        p.board[fr] = "."
        if piece.upper() == "P" and to == p.ep and target == ".":
            p.board[to + (8 if piece.isupper() else -8)] = "."
        if piece.upper() == "K" and abs(to - fr) == 2:
            if to == 62:
                p.board[61], p.board[63] = "R", "."
            elif to == 58:
                p.board[59], p.board[56] = "R", "."
            elif to == 6:
                p.board[5], p.board[7] = "r", "."
            elif to == 2:
                p.board[3], p.board[0] = "r", "."
        p.board[to] = promo.upper() if promo and piece.isupper() else (promo if promo else piece)
        p.ep = -1
        if piece.upper() == "P" and abs(to - fr) == 16:
            p.ep = (to + fr) // 2
        for flag, sq in (("K", 60), ("Q", 60), ("k", 4), ("q", 4)):
            if fr == sq:
                p.castle = p.castle.replace(flag, "")
        for flag, sq in (("Q", 56), ("K", 63), ("q", 0), ("k", 7)):
            if fr == sq or to == sq:
                p.castle = p.castle.replace(flag, "")
        p.halfmove = 0 if piece.upper() == "P" or target != "." else p.halfmove + 1
        if p.side == -1:
            p.fullmove += 1
        p.side = -p.side
        return p


def move_to_uci(m):
    return sq_name(m[0]) + sq_name(m[1]) + m[2]


def parse_uci(pos, text):
    if len(text) < 4:
        return None
    fr, to = parse_sq(text[:2]), parse_sq(text[2:4])
    promo = text[4].lower() if len(text) > 4 else ""
    for m in pos.legal_moves():
        if m[0] == fr and m[1] == to and m[2] == promo:
            return m
    return None


def evaluate(pos):
    score = 0
    bishops = {1: 0, -1: 0}
    pawns = {1: [0] * 8, -1: [0] * 8}
    for sq, p in enumerate(pos.board):
        if p == ".":
            continue
        s = color(p)
        up = p.upper()
        idx = sq if s == 1 else 63 - sq
        score += s * (VAL[up] + PST[up][idx])
        if up == "B":
            bishops[s] += 1
        if up == "P":
            pawns[s][sq % 8] += 1
    if bishops[1] >= 2:
        score += 35
    if bishops[-1] >= 2:
        score -= 35
    for s in (1, -1):
        for f, n in enumerate(pawns[s]):
            if n > 1:
                score -= s * 12 * (n - 1)
            if n and not ((f > 0 and pawns[s][f - 1]) or (f < 7 and pawns[s][f + 1])):
                score -= s * 10
    return score * pos.side


class SearchTimeout(Exception):
    pass


class Engine:
    def __init__(self):
        self.pos = Position()
        self.deadline = 0
        self.nodes = 0

    def check_time(self):
        self.nodes += 1
        if self.nodes & 1023 == 0 and time.perf_counter() >= self.deadline:
            raise SearchTimeout

    def order(self, pos, moves):
        def key(m):
            fr, to, promo = m
            victim = pos.board[to]
            mover = pos.board[fr]
            sc = 0
            if promo:
                sc += VAL[promo.upper()] + 800
            if victim != ".":
                sc += 10 * VAL[victim.upper()] - VAL[mover.upper()]
            if mover.upper() == "P" and to == pos.ep:
                sc += 1000
            if to in (27, 28, 35, 36):
                sc += 15
            return -sc
        return sorted(moves, key=key)

    def quiesce(self, pos, alpha, beta):
        self.check_time()
        stand = evaluate(pos)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        for m in self.order(pos, pos.legal_moves(True)):
            score = -self.quiesce(pos.make(m), -beta, -alpha)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def alphabeta(self, pos, depth, alpha, beta):
        self.check_time()
        if depth <= 0:
            return self.quiesce(pos, alpha, beta)
        moves = pos.legal_moves()
        if not moves:
            return -MATE + depth if pos.in_check() else 0
        for m in self.order(pos, moves):
            score = -self.alphabeta(pos.make(m), depth - 1, -beta, -alpha)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def bestmove(self, movetime):
        moves = self.pos.legal_moves()
        if not moves:
            return "0000"
        moves = self.order(self.pos, moves)
        best = moves[0]
        budget = max(0.005, movetime / 1000.0)
        self.deadline = time.perf_counter() + max(0.001, budget - 0.003)
        self.nodes = 0
        depth = 1
        try:
            while depth <= 5:
                local_best = best
                alpha = -INF
                for m in moves:
                    score = -self.alphabeta(self.pos.make(m), depth - 1, -INF, INF)
                    if score > alpha:
                        alpha = score
                        local_best = m
                best = local_best
                moves = [best] + [m for m in moves if m != best]
                depth += 1
                if time.perf_counter() >= self.deadline:
                    break
        except SearchTimeout:
            pass
        return move_to_uci(best)

    def set_position(self, args):
        try:
            if not args:
                return
            if args[0] == "startpos":
                self.pos.set_fen(START_FEN)
                rest = args[1:]
            elif args[0] == "fen":
                fen = " ".join(args[1:7])
                self.pos.set_fen(fen)
                rest = args[7:]
            else:
                return
            if rest and rest[0] == "moves":
                for mv in rest[1:]:
                    m = parse_uci(self.pos, mv)
                    if m is None:
                        break
                    self.pos = self.pos.make(m)
        except Exception:
            self.pos.set_fen(START_FEN)

    def loop(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            cmd = parts[0]
            if cmd == "uci":
                print("id name ScratchLegalAB")
                print("id author openai")
                print("uciok")
                sys.stdout.flush()
            elif cmd == "isready":
                print("readyok")
                sys.stdout.flush()
            elif cmd == "ucinewgame":
                self.pos.set_fen(START_FEN)
            elif cmd == "position":
                self.set_position(parts[1:])
            elif cmd == "go":
                mt = 20
                if "movetime" in parts:
                    try:
                        mt = int(parts[parts.index("movetime") + 1])
                    except Exception:
                        mt = 20
                print("bestmove " + self.bestmove(mt))
                sys.stdout.flush()
            elif cmd == "quit":
                break


if __name__ == "__main__":
    Engine().loop()

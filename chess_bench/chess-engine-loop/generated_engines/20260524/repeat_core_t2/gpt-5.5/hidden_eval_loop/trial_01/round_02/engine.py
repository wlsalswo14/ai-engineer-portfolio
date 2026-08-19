import sys
import time

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FILES = "abcdefgh"
RANKS = "12345678"
VAL = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
INF = 10 ** 9

PST_P = [0, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 50, 50, 50, 50, 50, 10, 10, 20, 30, 30, 20, 10, 10, 5, 5, 10, 25, 25, 10, 5, 5, 0, 0, 0, 20, 20, 0, 0, 0, 5, -5, -10, 0, 0, -10, -5, 5, 5, 10, 10, -20, -20, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0]
PST_N = [-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0, 5, 5, 0, -20, -40, -30, 5, 10, 15, 15, 10, 5, -30, -30, 0, 15, 20, 20, 15, 0, -30, -30, 5, 15, 20, 20, 15, 5, -30, -30, 0, 10, 15, 15, 10, 0, -30, -40, -20, 0, 0, 0, 0, -20, -40, -50, -40, -30, -30, -30, -30, -40, -50]
PST_B = [-20, -10, -10, -10, -10, -10, -10, -20, -10, 5, 0, 0, 0, 0, 5, -10, -10, 10, 10, 10, 10, 10, 10, -10, -10, 0, 10, 10, 10, 10, 0, -10, -10, 5, 5, 10, 10, 5, 5, -10, -10, 0, 5, 10, 10, 5, 0, -10, -10, 0, 0, 0, 0, 0, 0, -10, -20, -10, -10, -10, -10, -10, -10, -20]
PST_R = [0, 0, 0, 5, 5, 0, 0, 0, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, 5, 10, 10, 10, 10, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0]
PST_Q = [-20, -10, -10, -5, -5, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 5, 5, 5, 0, -10, -5, 0, 5, 5, 5, 5, 0, -5, 0, 0, 5, 5, 5, 5, 0, -5, -10, 5, 5, 5, 5, 5, 0, -10, -10, 0, 5, 0, 0, 0, 0, -10, -20, -10, -10, -5, -5, -10, -10, -20]
PST_K = [20, 30, 10, 0, 0, 10, 30, 20, 20, 20, 0, 0, 0, 0, 20, 20, -10, -20, -20, -20, -20, -20, -20, -10, -20, -30, -30, -40, -40, -30, -30, -20, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30]
PST = {"P": PST_P, "N": PST_N, "B": PST_B, "R": PST_R, "Q": PST_Q, "K": PST_K}


def sq_name(i):
    return FILES[i % 8] + RANKS[i // 8]


def sq_idx(s):
    if len(s) != 2 or s[0] not in FILES or s[1] not in RANKS:
        return -1
    return FILES.index(s[0]) + 8 * RANKS.index(s[1])


def color(p):
    return "w" if p.isupper() else "b"


class Position:
    def __init__(self):
        self.board = ["."] * 64
        self.side = "w"
        self.castle = ""
        self.ep = -1
        self.half = 0
        self.full = 1
        self.set_fen(START_FEN)

    def clone(self):
        q = Position.__new__(Position)
        q.board = self.board[:]
        q.side = self.side
        q.castle = self.castle
        q.ep = self.ep
        q.half = self.half
        q.full = self.full
        return q

    def set_fen(self, fen):
        parts = fen.strip().split()
        if len(parts) < 4:
            parts = START_FEN.split()
        b = []
        try:
            for rank in reversed(parts[0].split("/")):
                for ch in rank:
                    if ch.isdigit():
                        b.extend(["."] * int(ch))
                    else:
                        b.append(ch)
            if len(b) != 64:
                raise ValueError
            self.board = b
            self.side = parts[1] if parts[1] in ("w", "b") else "w"
            self.castle = "" if parts[2] == "-" else "".join(c for c in parts[2] if c in "KQkq")
            self.ep = -1 if parts[3] == "-" else sq_idx(parts[3])
            self.half = int(parts[4]) if len(parts) > 4 else 0
            self.full = int(parts[5]) if len(parts) > 5 else 1
        except Exception:
            self.set_fen(START_FEN)

    def king_square(self, side):
        k = "K" if side == "w" else "k"
        for i, p in enumerate(self.board):
            if p == k:
                return i
        return -1

    def attacked(self, sq, by_side):
        b = self.board
        f, r = sq % 8, sq // 8
        pawn_dirs = [(-1, -1), (1, -1)] if by_side == "w" else [(-1, 1), (1, 1)]
        pawn = "P" if by_side == "w" else "p"
        for df, dr in pawn_dirs:
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8 and b[nr * 8 + nf] == pawn:
                return True
        knight = "N" if by_side == "w" else "n"
        for df, dr in ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)):
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8 and b[nr * 8 + nf] == knight:
                return True
        bishop = "B" if by_side == "w" else "b"
        rook = "R" if by_side == "w" else "r"
        queen = "Q" if by_side == "w" else "q"
        for df, dr, sliders in ((1, 1, bishop + queen), (1, -1, bishop + queen), (-1, 1, bishop + queen), (-1, -1, bishop + queen), (1, 0, rook + queen), (-1, 0, rook + queen), (0, 1, rook + queen), (0, -1, rook + queen)):
            nf, nr = f + df, r + dr
            while 0 <= nf < 8 and 0 <= nr < 8:
                p = b[nr * 8 + nf]
                if p != ".":
                    if p in sliders:
                        return True
                    break
                nf += df
                nr += dr
        king = "K" if by_side == "w" else "k"
        for df in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if df or dr:
                    nf, nr = f + df, r + dr
                    if 0 <= nf < 8 and 0 <= nr < 8 and b[nr * 8 + nf] == king:
                        return True
        return False

    def in_check(self, side=None):
        side = side or self.side
        k = self.king_square(side)
        return k < 0 or self.attacked(k, "b" if side == "w" else "w")

    def pseudo_moves(self):
        moves = []
        us = self.side
        b = self.board
        for i, p in enumerate(b):
            if p == "." or color(p) != us:
                continue
            f, r = i % 8, i // 8
            up = 1 if us == "w" else -1
            if p.upper() == "P":
                one = i + 8 * up
                start = 1 if us == "w" else 6
                promo_rank = 7 if us == "w" else 0
                if 0 <= one < 64 and b[one] == ".":
                    if one // 8 == promo_rank:
                        for pr in "qrbn":
                            moves.append((i, one, pr))
                    else:
                        moves.append((i, one, ""))
                        two = i + 16 * up
                        if r == start and b[two] == ".":
                            moves.append((i, two, ""))
                for df in (-1, 1):
                    nf, nr = f + df, r + up
                    if 0 <= nf < 8 and 0 <= nr < 8:
                        to = nr * 8 + nf
                        if b[to] != "." and color(b[to]) != us or to == self.ep:
                            if nr == promo_rank:
                                for pr in "qrbn":
                                    moves.append((i, to, pr))
                            else:
                                moves.append((i, to, ""))
            elif p.upper() == "N":
                for df, dr in ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)):
                    nf, nr = f + df, r + dr
                    if 0 <= nf < 8 and 0 <= nr < 8:
                        to = nr * 8 + nf
                        if b[to] == "." or color(b[to]) != us:
                            moves.append((i, to, ""))
            elif p.upper() in "BRQ":
                dirs = []
                if p.upper() in "BQ":
                    dirs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
                if p.upper() in "RQ":
                    dirs += [(1, 0), (-1, 0), (0, 1), (0, -1)]
                for df, dr in dirs:
                    nf, nr = f + df, r + dr
                    while 0 <= nf < 8 and 0 <= nr < 8:
                        to = nr * 8 + nf
                        if b[to] == ".":
                            moves.append((i, to, ""))
                        else:
                            if color(b[to]) != us:
                                moves.append((i, to, ""))
                            break
                        nf += df
                        nr += dr
            elif p.upper() == "K":
                for df in (-1, 0, 1):
                    for dr in (-1, 0, 1):
                        if df or dr:
                            nf, nr = f + df, r + dr
                            if 0 <= nf < 8 and 0 <= nr < 8:
                                to = nr * 8 + nf
                                if b[to] == "." or color(b[to]) != us:
                                    moves.append((i, to, ""))
                if us == "w" and i == 4 and not self.in_check("w"):
                    if "K" in self.castle and b[5] == b[6] == "." and b[7] == "R" and not self.attacked(5, "b") and not self.attacked(6, "b"):
                        moves.append((4, 6, ""))
                    if "Q" in self.castle and b[1] == b[2] == b[3] == "." and b[0] == "R" and not self.attacked(3, "b") and not self.attacked(2, "b"):
                        moves.append((4, 2, ""))
                if us == "b" and i == 60 and not self.in_check("b"):
                    if "k" in self.castle and b[61] == b[62] == "." and b[63] == "r" and not self.attacked(61, "w") and not self.attacked(62, "w"):
                        moves.append((60, 62, ""))
                    if "q" in self.castle and b[57] == b[58] == b[59] == "." and b[56] == "r" and not self.attacked(59, "w") and not self.attacked(58, "w"):
                        moves.append((60, 58, ""))
        return moves

    def make(self, mv):
        fr, to, promo = mv
        b = self.board
        p = b[fr]
        cap = b[to]
        old_ep = self.ep
        b[fr] = "."
        if p.upper() == "P" and to == old_ep and cap == ".":
            b[to - (8 if self.side == "w" else -8)] = "."
        if p.upper() == "K" and abs(to - fr) == 2:
            if to == 6:
                b[5], b[7] = b[7], "."
            elif to == 2:
                b[3], b[0] = b[0], "."
            elif to == 62:
                b[61], b[63] = b[63], "."
            elif to == 58:
                b[59], b[56] = b[56], "."
        b[to] = promo.upper() if promo and self.side == "w" else promo if promo else p
        self.ep = -1
        if p.upper() == "P" and abs(to - fr) == 16:
            self.ep = (to + fr) // 2
        for c, sq in (("K", 4), ("Q", 4), ("k", 60), ("q", 60)):
            if fr == sq:
                self.castle = self.castle.replace(c, "")
        for c, sq in (("Q", 0), ("K", 7), ("q", 56), ("k", 63)):
            if fr == sq or to == sq:
                self.castle = self.castle.replace(c, "")
        if p.upper() == "P" or cap != ".":
            self.half = 0
        else:
            self.half += 1
        if self.side == "b":
            self.full += 1
        self.side = "b" if self.side == "w" else "w"

    def legal_moves(self):
        out = []
        us = self.side
        for mv in self.pseudo_moves():
            q = self.clone()
            q.make(mv)
            if not q.in_check(us):
                out.append(mv)
        return out

    def push_uci(self, s):
        if len(s) < 4:
            return False
        fr, to = sq_idx(s[:2]), sq_idx(s[2:4])
        pr = s[4].lower() if len(s) > 4 else ""
        for mv in self.legal_moves():
            if mv == (fr, to, pr):
                self.make(mv)
                return True
        return False


def move_str(mv):
    return sq_name(mv[0]) + sq_name(mv[1]) + mv[2]


def evaluate(pos):
    score = 0
    bishops = {"w": 0, "b": 0}
    for i, p in enumerate(pos.board):
        if p == ".":
            continue
        up = p.upper()
        s = VAL[up] + PST[up][i if p.isupper() else 63 - i]
        if up == "B":
            bishops[color(p)] += 1
        score += s if p.isupper() else -s
    if bishops["w"] >= 2:
        score += 35
    if bishops["b"] >= 2:
        score -= 35
    return score if pos.side == "w" else -score


def ordered(pos, moves):
    b = pos.board
    def key(mv):
        fr, to, pr = mv
        p, cap = b[fr], b[to]
        k = 0
        if pr:
            k += VAL[pr.upper()] + 800
        if cap != ".":
            k += 10 * VAL[cap.upper()] - VAL[p.upper()]
        if p.upper() in "PNBQ" and 24 <= to <= 39:
            k += 8
        return k
    return sorted(moves, key=key, reverse=True)


class SearchTimeout(Exception):
    pass


def negamax(pos, depth, alpha, beta, deadline, ply=0):
    if time.perf_counter() >= deadline:
        raise SearchTimeout
    moves = pos.legal_moves()
    if depth == 0 or not moves:
        if not moves:
            return -100000 + ply if pos.in_check() else 0
        return evaluate(pos)
    best = -INF
    for mv in ordered(pos, moves):
        q = pos.clone()
        q.make(mv)
        val = -negamax(q, depth - 1, -beta, -alpha, deadline, ply + 1)
        if val > best:
            best = val
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def choose_move(pos, ms):
    moves = pos.legal_moves()
    if not moves:
        return None
    best = ordered(pos, moves)[0]
    deadline = time.perf_counter() + max(0.005, (ms - 3) / 1000.0)
    max_depth = 4 if ms < 80 else 5
    for depth in range(1, max_depth + 1):
        try:
            local_best = best
            alpha = -INF
            for mv in ordered(pos, moves):
                q = pos.clone()
                q.make(mv)
                val = -negamax(q, depth - 1, -INF, -alpha, deadline, 1)
                if val > alpha:
                    alpha = val
                    local_best = mv
            best = local_best
        except SearchTimeout:
            break
    return best


def set_position(pos, args):
    if not args:
        return
    try:
        if args[0] == "startpos":
            pos.set_fen(START_FEN)
            rest = args[1:]
        elif args[0] == "fen" and len(args) >= 7:
            pos.set_fen(" ".join(args[1:7]))
            rest = args[7:]
        else:
            return
        if rest and rest[0] == "moves":
            for m in rest[1:]:
                if not pos.push_uci(m):
                    break
    except Exception:
        return


def main():
    pos = Position()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        if cmd == "uci":
            print("id name MinimalBenchEngine", flush=True)
            print("id author OpenAI", flush=True)
            print("uciok", flush=True)
        elif cmd == "isready":
            print("readyok", flush=True)
        elif cmd == "ucinewgame":
            pos = Position()
        elif cmd == "position":
            set_position(pos, parts[1:])
        elif cmd == "go":
            ms = 20
            if "movetime" in parts:
                try:
                    ms = int(parts[parts.index("movetime") + 1])
                except Exception:
                    ms = 20
            mv = choose_move(pos, ms)
            print("bestmove " + (move_str(mv) if mv else "0000"), flush=True)
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import sys
import time

FILES = "abcdefgh"
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
VAL = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
DIRS_B = (9, 7, -7, -9)
DIRS_R = (8, -8, 1, -1)
KNIGHT = (17, 15, 10, 6, -6, -10, -15, -17)
KING = (8, -8, 1, -1, 9, 7, -7, -9)
INF = 1000000


def sq_name(s):
    return FILES[s & 7] + str((s >> 3) + 1)


def parse_sq(t):
    if len(t) != 2 or t[0] not in FILES or t[1] not in "12345678":
        return -1
    return (int(t[1]) - 1) * 8 + FILES.index(t[0])


def same_line(a, b, d):
    if not 0 <= b < 64:
        return False
    af, bf = a & 7, b & 7
    if d in (1, -1):
        return (a >> 3) == (b >> 3)
    if d in (9, -9):
        return abs(af - bf) == 1
    if d in (7, -7):
        return abs(af - bf) == 1
    if d in (17, -15):
        return bf - af == 1
    if d in (15, -17):
        return af - bf == 1
    if d in (10, -6):
        return bf - af == 2
    if d in (6, -10):
        return af - bf == 2
    return True


class Move:
    __slots__ = ("a", "b", "p", "ep", "castle")

    def __init__(self, a, b, p="", ep=False, castle=False):
        self.a = a
        self.b = b
        self.p = p
        self.ep = ep
        self.castle = castle

    def uci(self):
        return sq_name(self.a) + sq_name(self.b) + self.p.lower()


class Pos:
    def __init__(self):
        self.b = ["."] * 64
        self.white = True
        self.castle = ""
        self.ep = -1
        self.half = 0
        self.full = 1
        self.set_fen(START)

    def clone(self):
        p = Pos.__new__(Pos)
        p.b = self.b[:]
        p.white = self.white
        p.castle = self.castle
        p.ep = self.ep
        p.half = self.half
        p.full = self.full
        return p

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            parts = START.split()
        self.b = ["."] * 64
        ranks = parts[0].split("/")
        for ri, row in enumerate(ranks[:8]):
            f = 0
            r = 7 - ri
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif f < 8:
                    self.b[r * 8 + f] = ch
                    f += 1
        self.white = parts[1] != "b"
        self.castle = "" if parts[2] == "-" else parts[2]
        self.ep = parse_sq(parts[3]) if parts[3] != "-" else -1
        self.half = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.full = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

    def king_sq(self, white):
        k = "K" if white else "k"
        try:
            return self.b.index(k)
        except ValueError:
            return -1

    def attacked(self, sq, by_white):
        pawns = (-7, -9) if by_white else (7, 9)
        for d in pawns:
            s = sq + d
            if 0 <= s < 64 and same_line(sq, s, d) and self.b[s] == ("P" if by_white else "p"):
                return True
        for d in KNIGHT:
            s = sq + d
            if 0 <= s < 64 and same_line(sq, s, d) and self.b[s] == ("N" if by_white else "n"):
                return True
        for d in DIRS_B:
            s = sq + d
            while 0 <= s < 64 and same_line(s - d, s, d):
                pc = self.b[s]
                if pc != ".":
                    if (pc.isupper() == by_white) and pc.upper() in "BQ":
                        return True
                    break
                s += d
        for d in DIRS_R:
            s = sq + d
            while 0 <= s < 64 and same_line(s - d, s, d):
                pc = self.b[s]
                if pc != ".":
                    if (pc.isupper() == by_white) and pc.upper() in "RQ":
                        return True
                    break
                s += d
        for d in KING:
            s = sq + d
            if 0 <= s < 64 and same_line(sq, s, d) and self.b[s] == ("K" if by_white else "k"):
                return True
        return False

    def in_check(self, white=None):
        if white is None:
            white = self.white
        k = self.king_sq(white)
        return k < 0 or self.attacked(k, not white)

    def make(self, m):
        p = self.clone()
        pc = p.b[m.a]
        cap = p.b[m.b]
        p.b[m.a] = "."
        if m.ep:
            p.b[m.b + (-8 if pc.isupper() else 8)] = "."
        p.b[m.b] = (m.p.upper() if pc.isupper() else m.p.lower()) if m.p else pc
        if m.castle:
            if m.b == 6:
                p.b[5], p.b[7] = p.b[7], "."
            elif m.b == 2:
                p.b[3], p.b[0] = p.b[0], "."
            elif m.b == 62:
                p.b[61], p.b[63] = p.b[63], "."
            elif m.b == 58:
                p.b[59], p.b[56] = p.b[56], "."
        for c, sq in (("K", 4), ("Q", 4), ("k", 60), ("q", 60)):
            if m.a == sq or m.b in (0, 7, 56, 63):
                p.castle = p.castle.replace(c, "")
        if pc == "R" and m.a == 0:
            p.castle = p.castle.replace("Q", "")
        if pc == "R" and m.a == 7:
            p.castle = p.castle.replace("K", "")
        if pc == "r" and m.a == 56:
            p.castle = p.castle.replace("q", "")
        if pc == "r" and m.a == 63:
            p.castle = p.castle.replace("k", "")
        if pc.upper() == "K":
            p.castle = p.castle.replace("K" if pc.isupper() else "k", "")
            p.castle = p.castle.replace("Q" if pc.isupper() else "q", "")
        p.ep = -1
        if pc.upper() == "P" and abs(m.b - m.a) == 16:
            p.ep = (m.a + m.b) // 2
        p.half = 0 if pc.upper() == "P" or cap != "." or m.ep else p.half + 1
        if not p.white:
            p.full += 1
        p.white = not p.white
        return p

    def pseudo(self):
        res = []
        white = self.white
        for s, pc in enumerate(self.b):
            if pc == "." or pc.isupper() != white:
                continue
            up = pc.upper()
            if up == "P":
                step = 8 if white else -8
                start = 1 if white else 6
                promo = 7 if white else 0
                one = s + step
                if 0 <= one < 64 and self.b[one] == ".":
                    if one >> 3 == promo:
                        for q in "qrbn":
                            res.append(Move(s, one, q))
                    else:
                        res.append(Move(s, one))
                        two = s + step * 2
                        if s >> 3 == start and self.b[two] == ".":
                            res.append(Move(s, two))
                for d in (step + 1, step - 1):
                    t = s + d
                    if not (0 <= t < 64 and same_line(s, t, d)):
                        continue
                    target = self.b[t]
                    if target != "." and target.isupper() != white:
                        if t >> 3 == promo:
                            for q in "qrbn":
                                res.append(Move(s, t, q))
                        else:
                            res.append(Move(s, t))
                    elif t == self.ep:
                        res.append(Move(s, t, ep=True))
            elif up == "N":
                for d in KNIGHT:
                    t = s + d
                    if 0 <= t < 64 and same_line(s, t, d) and (self.b[t] == "." or self.b[t].isupper() != white):
                        res.append(Move(s, t))
            elif up in "BRQ":
                dirs = DIRS_B if up == "B" else DIRS_R if up == "R" else DIRS_B + DIRS_R
                for d in dirs:
                    t = s + d
                    while 0 <= t < 64 and same_line(t - d, t, d):
                        if self.b[t] == ".":
                            res.append(Move(s, t))
                        else:
                            if self.b[t].isupper() != white:
                                res.append(Move(s, t))
                            break
                        t += d
            elif up == "K":
                for d in KING:
                    t = s + d
                    if 0 <= t < 64 and same_line(s, t, d) and (self.b[t] == "." or self.b[t].isupper() != white):
                        res.append(Move(s, t))
                if white and s == 4 and not self.in_check(True):
                    if "K" in self.castle and self.b[5] == self.b[6] == "." and not self.attacked(5, False) and not self.attacked(6, False):
                        res.append(Move(4, 6, castle=True))
                    if "Q" in self.castle and self.b[1] == self.b[2] == self.b[3] == "." and not self.attacked(3, False) and not self.attacked(2, False):
                        res.append(Move(4, 2, castle=True))
                if not white and s == 60 and not self.in_check(False):
                    if "k" in self.castle and self.b[61] == self.b[62] == "." and not self.attacked(61, True) and not self.attacked(62, True):
                        res.append(Move(60, 62, castle=True))
                    if "q" in self.castle and self.b[57] == self.b[58] == self.b[59] == "." and not self.attacked(59, True) and not self.attacked(58, True):
                        res.append(Move(60, 58, castle=True))
        return res

    def legal(self):
        side = self.white
        out = []
        for m in self.pseudo():
            if not self.make(m).in_check(side):
                out.append(m)
        return out


PST_P = [0, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 50, 50, 50, 50, 50, 10, 10, 20, 30, 30, 20, 10, 10, 5, 5, 10, 25, 25, 10, 5, 5, 0, 0, 0, 20, 20, 0, 0, 0, 5, -5, -10, 0, 0, -10, -5, 5, 5, 10, 10, -20, -20, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0]
PST_N = [-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0, 5, 5, 0, -20, -40, -30, 5, 10, 15, 15, 10, 5, -30, -30, 0, 15, 20, 20, 15, 0, -30, -30, 5, 15, 20, 20, 15, 5, -30, -30, 0, 10, 15, 15, 10, 0, -30, -40, -20, 0, 0, 0, 0, -20, -40, -50, -40, -30, -30, -30, -30, -40, -50]
PST_B = [-20, -10, -10, -10, -10, -10, -10, -20, -10, 5, 0, 0, 0, 0, 5, -10, -10, 10, 10, 10, 10, 10, 10, -10, -10, 0, 10, 10, 10, 10, 0, -10, -10, 5, 5, 10, 10, 5, 5, -10, -10, 0, 5, 10, 10, 5, 0, -10, -10, 0, 0, 0, 0, 0, 0, -10, -20, -10, -10, -10, -10, -10, -10, -20]
PST_R = [0, 0, 0, 5, 5, 0, 0, 0, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, 5, 10, 10, 10, 10, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0]
PST_Q = [-20, -10, -10, -5, -5, -10, -10, -20, -10, 0, 5, 0, 0, 0, 0, -10, -10, 5, 5, 5, 5, 5, 0, -10, 0, 0, 5, 5, 5, 5, 0, -5, -5, 0, 5, 5, 5, 5, 0, -5, -10, 0, 5, 5, 5, 5, 0, -10, -10, 0, 0, 0, 0, 0, 0, -10, -20, -10, -10, -5, -5, -10, -10, -20]
PST_K = [20, 30, 10, 0, 0, 10, 30, 20, 20, 20, 0, 0, 0, 0, 20, 20, -10, -20, -20, -20, -20, -20, -20, -10, -20, -30, -30, -40, -40, -30, -30, -20, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30]
PSTS = {"P": PST_P, "N": PST_N, "B": PST_B, "R": PST_R, "Q": PST_Q, "K": PST_K}


def pst(pc, sq):
    a = pc.upper()
    idx = sq if pc.isupper() else 63 - sq
    return PSTS[a][idx]


def evaluate(pos):
    score = 0
    bishops = [0, 0]
    for s, pc in enumerate(pos.b):
        if pc == ".":
            continue
        v = VAL[pc.upper()] + pst(pc, s)
        if pc.upper() == "B":
            bishops[0 if pc.isupper() else 1] += 1
        score += v if pc.isupper() else -v
    if bishops[0] >= 2:
        score += 35
    if bishops[1] >= 2:
        score -= 35
    return score if pos.white else -score


class Search:
    def __init__(self, end):
        self.end = end
        self.nodes = 0

    def order(self, pos, moves):
        def key(m):
            pc = pos.b[m.a].upper()
            cap = "P" if m.ep else pos.b[m.b].upper()
            v = 0
            if cap != ".":
                v += 10 * VAL.get(cap, 0) - VAL.get(pc, 0)
            if m.p:
                v += VAL[m.p.upper()]
            if m.castle:
                v += 30
            return v
        moves.sort(key=key, reverse=True)
        return moves

    def qsearch(self, pos, alpha, beta):
        stand = evaluate(pos)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        if time.monotonic() > self.end:
            return alpha
        caps = [m for m in pos.legal() if pos.b[m.b] != "." or m.ep or m.p]
        for m in self.order(pos, caps):
            score = -self.qsearch(pos.make(m), -beta, -alpha)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def negamax(self, pos, depth, alpha, beta):
        self.nodes += 1
        if self.nodes & 63 == 0 and time.monotonic() > self.end:
            raise TimeoutError
        if depth <= 0:
            return evaluate(pos)
        moves = pos.legal()
        if not moves:
            return -100000 + depth if pos.in_check() else 0
        best = -INF
        for m in self.order(pos, moves):
            score = -self.negamax(pos.make(m), depth - 1, -beta, -alpha)
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        return best

    def best(self, pos, ms):
        moves = pos.legal()
        if not moves:
            return None
        best = self.order(pos, moves)[0]
        if ms <= 30:
            return best
        end_soft = time.monotonic() + max(0.003, ms / 1000.0 * 0.55)
        self.end = end_soft
        depth = 1
        max_depth = 3
        while depth <= max_depth:
            try:
                alpha = -INF
                cur = best
                for m in self.order(pos, moves[:]):
                    score = -self.negamax(pos.make(m), depth - 1, -INF, -alpha)
                    if score > alpha:
                        alpha = score
                        cur = m
                    if time.monotonic() > self.end:
                        raise TimeoutError
                best = cur
                depth += 1
            except TimeoutError:
                break
        return best


def apply_uci(pos, mv):
    if len(mv) < 4:
        return pos
    a, b = parse_sq(mv[:2]), parse_sq(mv[2:4])
    promo = mv[4].lower() if len(mv) > 4 else ""
    for m in pos.legal():
        if m.a == a and m.b == b and (m.p.lower() if m.p else "") == promo:
            return pos.make(m)
    return pos


def set_position(pos, args):
    try:
        if not args:
            return pos
        i = 0
        if args[0] == "startpos":
            pos = Pos()
            i = 1
        elif args[0] == "fen" and len(args) >= 7:
            pos = Pos()
            pos.set_fen(" ".join(args[1:7]))
            i = 7
        if i < len(args) and args[i] == "moves":
            for mv in args[i + 1:]:
                pos = apply_uci(pos, mv)
        return pos
    except Exception:
        return Pos()


def main():
    pos = Pos()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        try:
            if cmd == "uci":
                print("id name PlainPythonBench")
                print("id author OpenAI")
                print("uciok", flush=True)
            elif cmd == "isready":
                print("readyok", flush=True)
            elif cmd == "ucinewgame":
                pos = Pos()
            elif cmd == "position":
                pos = set_position(pos, parts[1:])
            elif cmd == "go":
                ms = 20
                if "movetime" in parts:
                    j = parts.index("movetime")
                    if j + 1 < len(parts):
                        ms = max(1, int(parts[j + 1]))
                m = Search(time.monotonic()).best(pos, ms)
                print("bestmove " + (m.uci() if m else "0000"), flush=True)
            elif cmd == "quit":
                break
        except Exception:
            print("bestmove 0000", flush=True)


if __name__ == "__main__":
    main()

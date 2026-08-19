import sys
import time

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
INF = 10**9
MATE = 100000

VAL = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
DIRS_B = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
DIRS_R = [(-1, 0), (1, 0), (0, -1), (0, 1)]
KNIGHT = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
KING = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

PST = {
    "P": [0, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 50, 50, 50, 50, 50, 10, 10, 20, 30, 30, 20, 10, 10, 5, 5, 10, 25, 25, 10, 5, 5, 0, 0, 0, 20, 20, 0, 0, 0, 5, -5, -10, 0, 0, -10, -5, 5, 5, 10, 10, -20, -20, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0],
    "N": [-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0, 5, 5, 0, -20, -40, -30, 5, 10, 15, 15, 10, 5, -30, -30, 0, 15, 20, 20, 15, 0, -30, -30, 5, 15, 20, 20, 15, 5, -30, -30, 0, 10, 15, 15, 10, 0, -30, -40, -20, 0, 0, 0, 0, -20, -40, -50, -40, -30, -30, -30, -30, -40, -50],
    "B": [-20, -10, -10, -10, -10, -10, -10, -20, -10, 5, 0, 0, 0, 0, 5, -10, -10, 10, 10, 10, 10, 10, 10, -10, -10, 0, 10, 10, 10, 10, 0, -10, -10, 5, 5, 10, 10, 5, 5, -10, -10, 0, 5, 10, 10, 5, 0, -10, -10, 0, 0, 0, 0, 0, 0, -10, -20, -10, -10, -10, -10, -10, -10, -20],
    "R": [0, 0, 0, 5, 5, 0, 0, 0, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, 5, 10, 10, 10, 10, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0],
    "Q": [-20, -10, -10, -5, -5, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10, -10, 0, 5, 5, 5, 5, 0, -10, -5, 0, 5, 5, 5, 5, 0, -5, 0, 0, 5, 5, 5, 5, 0, -5, -10, 5, 5, 5, 5, 5, 0, -10, -10, 0, 5, 0, 0, 0, 0, -10, -20, -10, -10, -5, -5, -10, -10, -20],
    "K": [20, 30, 10, 0, 0, 10, 30, 20, 20, 20, 0, 0, 0, 0, 20, 20, -10, -20, -20, -20, -20, -20, -20, -10, -20, -30, -30, -40, -40, -30, -30, -20, -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30, -30],
}


def sq(name):
    return (8 - int(name[1])) * 8 + ord(name[0]) - 97


def name(i):
    return chr(97 + i % 8) + str(8 - i // 8)


def enemy(side):
    return "b" if side == "w" else "w"


def color(p):
    return "w" if p.isupper() else "b"


class Pos:
    def __init__(self):
        self.set_fen(START_FEN)

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            parts = START_FEN.split()
        self.b = ["."] * 64
        rows = parts[0].split("/")
        if len(rows) != 8:
            rows = START_FEN.split()[0].split("/")
        for r, row in enumerate(rows):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif f < 8:
                    self.b[r * 8 + f] = ch
                    f += 1
        self.side = parts[1] if parts[1] in ("w", "b") else "w"
        self.castle = parts[2] if len(parts) > 2 and parts[2] != "-" else ""
        self.ep = -1 if len(parts) < 4 or parts[3] == "-" else sq(parts[3])
        self.half = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.full = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

    def clone(self):
        p = Pos.__new__(Pos)
        p.b = self.b[:]
        p.side = self.side
        p.castle = self.castle
        p.ep = self.ep
        p.half = self.half
        p.full = self.full
        return p

    def king_sq(self, side):
        k = "K" if side == "w" else "k"
        for i, p in enumerate(self.b):
            if p == k:
                return i
        return -1

    def attacked(self, at, by):
        r, f = divmod(at, 8)
        pd = 1 if by == "w" else -1
        for df in (-1, 1):
            rr, ff = r + pd, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and self.b[rr * 8 + ff] == ("P" if by == "w" else "p"):
                return True
        for dr, df in KNIGHT:
            rr, ff = r + dr, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and self.b[rr * 8 + ff] == ("N" if by == "w" else "n"):
                return True
        for dirs, pieces in ((DIRS_B, "BQ"), (DIRS_R, "RQ")):
            for dr, df in dirs:
                rr, ff = r + dr, f + df
                while 0 <= rr < 8 and 0 <= ff < 8:
                    q = self.b[rr * 8 + ff]
                    if q != ".":
                        if color(q) == by and q.upper() in pieces:
                            return True
                        break
                    rr += dr
                    ff += df
        for dr, df in KING:
            rr, ff = r + dr, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and self.b[rr * 8 + ff] == ("K" if by == "w" else "k"):
                return True
        return False

    def in_check(self, side):
        k = self.king_sq(side)
        return k < 0 or self.attacked(k, enemy(side))

    def pseudo(self):
        side = self.side
        out = []
        for i, p in enumerate(self.b):
            if p == "." or color(p) != side:
                continue
            r, f = divmod(i, 8)
            up = p.upper()
            if up == "P":
                step = -1 if side == "w" else 1
                start = 6 if side == "w" else 1
                promo = 0 if side == "w" else 7
                one_r = r + step
                if 0 <= one_r < 8:
                    one = one_r * 8 + f
                    if self.b[one] == ".":
                        if one_r == promo:
                            for pr in "qrbn":
                                out.append((i, one, pr))
                        else:
                            out.append((i, one, ""))
                            two = (r + 2 * step) * 8 + f
                            if r == start and self.b[two] == ".":
                                out.append((i, two, ""))
                    for df in (-1, 1):
                        ff = f + df
                        if 0 <= ff < 8:
                            to = one_r * 8 + ff
                            q = self.b[to]
                            if (q != "." and color(q) != side) or to == self.ep:
                                if one_r == promo:
                                    for pr in "qrbn":
                                        out.append((i, to, pr))
                                else:
                                    out.append((i, to, ""))
            elif up == "N":
                for dr, df in KNIGHT:
                    rr, ff = r + dr, f + df
                    if 0 <= rr < 8 and 0 <= ff < 8:
                        to = rr * 8 + ff
                        q = self.b[to]
                        if q == "." or color(q) != side:
                            out.append((i, to, ""))
            elif up in "BRQ":
                dirs = (DIRS_B if up == "B" else DIRS_R if up == "R" else DIRS_B + DIRS_R)
                for dr, df in dirs:
                    rr, ff = r + dr, f + df
                    while 0 <= rr < 8 and 0 <= ff < 8:
                        to = rr * 8 + ff
                        q = self.b[to]
                        if q == ".":
                            out.append((i, to, ""))
                        else:
                            if color(q) != side:
                                out.append((i, to, ""))
                            break
                        rr += dr
                        ff += df
            elif up == "K":
                for dr, df in KING:
                    rr, ff = r + dr, f + df
                    if 0 <= rr < 8 and 0 <= ff < 8:
                        to = rr * 8 + ff
                        q = self.b[to]
                        if q == "." or color(q) != side:
                            out.append((i, to, ""))
                if side == "w" and i == 60 and not self.in_check("w"):
                    if "K" in self.castle and self.b[61] == self.b[62] == "." and not self.attacked(61, "b") and not self.attacked(62, "b"):
                        out.append((60, 62, ""))
                    if "Q" in self.castle and self.b[59] == self.b[58] == self.b[57] == "." and not self.attacked(59, "b") and not self.attacked(58, "b"):
                        out.append((60, 58, ""))
                if side == "b" and i == 4 and not self.in_check("b"):
                    if "k" in self.castle and self.b[5] == self.b[6] == "." and not self.attacked(5, "w") and not self.attacked(6, "w"):
                        out.append((4, 6, ""))
                    if "q" in self.castle and self.b[3] == self.b[2] == self.b[1] == "." and not self.attacked(3, "w") and not self.attacked(2, "w"):
                        out.append((4, 2, ""))
        return out

    def legal(self):
        side = self.side
        ans = []
        for m in self.pseudo():
            p = self.clone()
            p.push(m)
            if not p.in_check(side):
                ans.append(m)
        return ans

    def push(self, m):
        fr, to, pr = m
        piece = self.b[fr]
        cap = self.b[to]
        side = self.side
        self.b[fr] = "."
        if piece.upper() == "P" and to == self.ep and cap == ".":
            self.b[to + (8 if side == "w" else -8)] = "."
        self.b[to] = (pr.upper() if side == "w" else pr) if pr else piece
        if piece == "K":
            self.castle = self.castle.replace("K", "").replace("Q", "")
            if fr == 60 and to == 62:
                self.b[63], self.b[61] = ".", "R"
            elif fr == 60 and to == 58:
                self.b[56], self.b[59] = ".", "R"
        elif piece == "k":
            self.castle = self.castle.replace("k", "").replace("q", "")
            if fr == 4 and to == 6:
                self.b[7], self.b[5] = ".", "r"
            elif fr == 4 and to == 2:
                self.b[0], self.b[3] = ".", "r"
        for c, s in (("Q", 56), ("K", 63), ("q", 0), ("k", 7)):
            if fr == s or to == s:
                self.castle = self.castle.replace(c, "")
        self.ep = -1
        if piece.upper() == "P" and abs(to - fr) == 16:
            self.ep = (to + fr) // 2
        self.half = 0 if piece.upper() == "P" or cap != "." else self.half + 1
        if side == "b":
            self.full += 1
        self.side = enemy(side)

    def move_from_uci(self, u):
        if len(u) < 4:
            return None
        try:
            fr, to = sq(u[:2]), sq(u[2:4])
        except Exception:
            return None
        pr = u[4].lower() if len(u) > 4 else ""
        for m in self.legal():
            if m == (fr, to, pr):
                return m
        return None


def mstr(m):
    return name(m[0]) + name(m[1]) + m[2]


def evaluate(pos):
    score = 0
    bishops = {"w": 0, "b": 0}
    pawns = {"w": [0] * 8, "b": [0] * 8}
    for i, p in enumerate(pos.b):
        if p == ".":
            continue
        side = color(p)
        u = p.upper()
        v = VAL[u]
        idx = i if side == "w" else 63 - i
        v += PST[u][idx]
        if u == "B":
            bishops[side] += 1
        if u == "P":
            pawns[side][i % 8] += 1
        score += v if side == "w" else -v
    if bishops["w"] >= 2:
        score += 25
    if bishops["b"] >= 2:
        score -= 25
    for f in range(8):
        if pawns["w"][f] > 1:
            score -= 12 * (pawns["w"][f] - 1)
        if pawns["b"][f] > 1:
            score += 12 * (pawns["b"][f] - 1)
    return score if pos.side == "w" else -score


class Search:
    def __init__(self, deadline):
        self.deadline = deadline
        self.nodes = 0

    def stop(self):
        return time.monotonic() >= self.deadline

    def ordered(self, pos, moves):
        def key(m):
            fr, to, pr = m
            a = pos.b[fr].upper()
            c = pos.b[to]
            s = 0
            if c != ".":
                s += 10 * VAL[c.upper()] - VAL[a]
            if pr:
                s += VAL[pr.upper()]
            if a == "P" and to == pos.ep:
                s += 90
            return -s
        return sorted(moves, key=key)

    def qsearch(self, pos, alpha, beta):
        stand = evaluate(pos)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        caps = []
        for m in pos.legal():
            if pos.b[m[1]] != "." or m[2] or (pos.b[m[0]].upper() == "P" and m[1] == pos.ep):
                caps.append(m)
        for m in self.ordered(pos, caps):
            if self.stop():
                raise TimeoutError
            p = pos.clone()
            p.push(m)
            score = -self.qsearch(p, -beta, -alpha)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def negamax(self, pos, depth, alpha, beta, ply=0):
        if self.stop():
            raise TimeoutError
        self.nodes += 1
        moves = pos.legal()
        if not moves:
            return -MATE + ply if pos.in_check(pos.side) else 0
        if depth <= 0:
            return self.qsearch(pos, alpha, beta)
        best = -INF
        for m in self.ordered(pos, moves):
            p = pos.clone()
            p.push(m)
            score = -self.negamax(p, depth - 1, -beta, -alpha, ply + 1)
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
        best = self.ordered(pos, moves)[0]
        budget = max(0.005, min(ms / 1000.0, 5.0))
        self.deadline = time.monotonic() + budget * 0.75
        max_depth = 2 if ms < 30 else 3 if ms < 150 else 4
        for depth in range(1, max_depth + 1):
            try:
                alpha = -INF
                local = best
                for m in self.ordered(pos, moves):
                    if self.stop():
                        raise TimeoutError
                    p = pos.clone()
                    p.push(m)
                    score = -self.negamax(p, depth - 1, -INF, -alpha, 1)
                    if score > alpha:
                        alpha = score
                        local = m
                best = local
            except TimeoutError:
                break
        return best


def set_position(pos, parts):
    try:
        if not parts:
            return
        moves_at = len(parts)
        if "moves" in parts:
            moves_at = parts.index("moves")
        if parts[0] == "startpos":
            pos.set_fen(START_FEN)
        elif parts[0] == "fen" and moves_at >= 7:
            pos.set_fen(" ".join(parts[1:7]))
        for u in parts[moves_at + 1:]:
            m = pos.move_from_uci(u)
            if m is None:
                break
            pos.push(m)
    except Exception:
        pos.set_fen(START_FEN)


def main():
    pos = Pos()
    for line in sys.stdin:
        cmd = line.strip()
        if not cmd:
            continue
        parts = cmd.split()
        if parts[0] == "uci":
            print("id name SimpleLegalPy")
            print("id author OpenAI")
            print("uciok")
            sys.stdout.flush()
        elif parts[0] == "isready":
            print("readyok")
            sys.stdout.flush()
        elif parts[0] == "ucinewgame":
            pos.set_fen(START_FEN)
        elif parts[0] == "position":
            set_position(pos, parts[1:])
        elif parts[0] == "go":
            ms = 20
            if "movetime" in parts:
                try:
                    ms = int(parts[parts.index("movetime") + 1])
                except Exception:
                    ms = 20
            try:
                move = Search(time.monotonic()).best(pos, ms)
                print("bestmove " + (mstr(move) if move else "0000"))
            except Exception:
                moves = pos.legal()
                print("bestmove " + (mstr(moves[0]) if moves else "0000"))
            sys.stdout.flush()
        elif parts[0] == "quit":
            break


if __name__ == "__main__":
    main()

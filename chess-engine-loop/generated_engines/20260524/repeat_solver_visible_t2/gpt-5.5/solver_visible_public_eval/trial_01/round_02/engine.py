#!/usr/bin/env python3
import sys
import time

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
INF = 10**9
MATE = 100000
FILES = "abcdefgh"
VAL = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}

KNIGHT = (-17, -15, -10, -6, 6, 10, 15, 17)
KING = (-9, -8, -7, -1, 1, 7, 8, 9)
ORTH = (1, -1, 8, -8)
DIAG = (9, -9, 7, -7)


def sq_name(i):
    return FILES[i & 7] + str((i >> 3) + 1)


def parse_sq(s):
    if len(s) != 2 or s[0] not in FILES or s[1] not in "12345678":
        return -1
    return (int(s[1]) - 1) * 8 + FILES.index(s[0])


def color(p):
    if p == ".":
        return None
    return "w" if p.isupper() else "b"


def opp(c):
    return "b" if c == "w" else "w"


def edge_ok(frm, to):
    return 0 <= to < 64 and abs((to & 7) - (frm & 7)) <= 1


class Move:
    __slots__ = ("a", "b", "promo", "ep", "castle")

    def __init__(self, a, b, promo="", ep=False, castle=False):
        self.a = a
        self.b = b
        self.promo = promo
        self.ep = ep
        self.castle = castle

    def uci(self):
        return sq_name(self.a) + sq_name(self.b) + self.promo


class Position:
    def __init__(self):
        self.board = ["."] * 64
        self.side = "w"
        self.castle = "-"
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.set_fen(START_FEN)

    def set_fen(self, fen):
        parts = fen.strip().split()
        if len(parts) < 4:
            parts = START_FEN.split()
        rows = parts[0].split("/")
        if len(rows) != 8:
            rows = START_FEN.split()[0].split("/")
        self.board = ["."] * 64
        for r, row in enumerate(reversed(rows)):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif f < 8 and ch in "PNBRQKpnbrqk":
                    self.board[r * 8 + f] = ch
                    f += 1
        self.side = parts[1] if len(parts) > 1 and parts[1] in ("w", "b") else "w"
        self.castle = parts[2] if len(parts) > 2 and parts[2] != "-" else "-"
        self.ep = parse_sq(parts[3]) if len(parts) > 3 and parts[3] != "-" else -1
        try:
            self.halfmove = int(parts[4]) if len(parts) > 4 else 0
            self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        except ValueError:
            self.halfmove, self.fullmove = 0, 1

    def king_sq(self, side):
        k = "K" if side == "w" else "k"
        return self.board.index(k) if k in self.board else -1

    def attacked(self, sq, by):
        b = self.board
        f = sq & 7
        if by == "w":
            for d in (-9, -7):
                t = sq + d
                if 0 <= t < 64 and abs((t & 7) - f) == 1 and b[t] == "P":
                    return True
        else:
            for d in (7, 9):
                t = sq + d
                if 0 <= t < 64 and abs((t & 7) - f) == 1 and b[t] == "p":
                    return True
        n = "N" if by == "w" else "n"
        for d in KNIGHT:
            t = sq + d
            if 0 <= t < 64 and max(abs((t & 7) - f), abs((t >> 3) - (sq >> 3))) == 2 and b[t] == n:
                return True
        for dirs, pieces in ((ORTH, "RQ"), (DIAG, "BQ")):
            for d in dirs:
                t = sq + d
                while edge_ok(t - d, t):
                    p = b[t]
                    if p != ".":
                        if color(p) == by and p.upper() in pieces:
                            return True
                        break
                    t += d
        k = "K" if by == "w" else "k"
        for d in KING:
            t = sq + d
            if edge_ok(sq, t) and b[t] == k:
                return True
        return False

    def in_check(self, side):
        k = self.king_sq(side)
        return k < 0 or self.attacked(k, opp(side))

    def make(self, m):
        b = self.board
        p, cap = b[m.a], b[m.b]
        old = (m, p, cap, self.castle, self.ep, self.halfmove, self.fullmove)
        b[m.a] = "."
        if m.ep:
            cap_sq = m.b - 8 if self.side == "w" else m.b + 8
            old += (cap_sq, b[cap_sq])
            b[cap_sq] = "."
        b[m.b] = (m.promo.upper() if self.side == "w" else m.promo.lower()) if m.promo else p
        if m.castle:
            if m.b == 6:
                b[5], b[7] = b[7], "."
            elif m.b == 2:
                b[3], b[0] = b[0], "."
            elif m.b == 62:
                b[61], b[63] = b[63], "."
            elif m.b == 58:
                b[59], b[56] = b[56], "."
        self.ep = -1
        if p.upper() == "P" and abs(m.b - m.a) == 16:
            self.ep = (m.a + m.b) // 2
        if p == "K" or m.a == 7 or m.b == 7:
            self.castle = self.castle.replace("K", "")
        if p == "K" or m.a == 0 or m.b == 0:
            self.castle = self.castle.replace("Q", "")
        if p == "k" or m.a == 63 or m.b == 63:
            self.castle = self.castle.replace("k", "")
        if p == "k" or m.a == 56 or m.b == 56:
            self.castle = self.castle.replace("q", "")
        if not self.castle:
            self.castle = "-"
        self.halfmove = 0 if p.upper() == "P" or cap != "." or m.ep else self.halfmove + 1
        if self.side == "b":
            self.fullmove += 1
        self.side = opp(self.side)
        return old

    def unmake(self, old):
        m, p, cap, self.castle, self.ep, self.halfmove, self.fullmove = old[:7]
        self.side = opp(self.side)
        self.board[m.a], self.board[m.b] = p, cap
        if m.ep:
            self.board[old[7]] = old[8]
            self.board[m.b] = "."
        if m.castle:
            if m.b == 6:
                self.board[7], self.board[5] = self.board[5], "."
            elif m.b == 2:
                self.board[0], self.board[3] = self.board[3], "."
            elif m.b == 62:
                self.board[63], self.board[61] = self.board[61], "."
            elif m.b == 58:
                self.board[56], self.board[59] = self.board[59], "."

    def pseudo(self, captures_only=False):
        out = []
        own = self.side
        enemy = opp(own)
        b = self.board
        for i, p in enumerate(b):
            if color(p) != own:
                continue
            r, f = divmod(i, 8)
            up = p.isupper()
            u = p.upper()
            if u == "P":
                step = 8 if up else -8
                start, promor = (1, 6) if up else (6, 1)
                one = i + step
                if not captures_only and 0 <= one < 64 and b[one] == ".":
                    if r == promor:
                        for pr in "qrbn":
                            out.append(Move(i, one, pr))
                    else:
                        out.append(Move(i, one))
                        two = i + 2 * step
                        if r == start and b[two] == ".":
                            out.append(Move(i, two))
                for df in (-1, 1):
                    if 0 <= f + df < 8:
                        t = i + step + df
                        if 0 <= t < 64 and (color(b[t]) == enemy or t == self.ep):
                            if r == promor:
                                for pr in "qrbn":
                                    out.append(Move(i, t, pr, t == self.ep))
                            else:
                                out.append(Move(i, t, "", t == self.ep))
            elif u == "N":
                for d in KNIGHT:
                    t = i + d
                    if 0 <= t < 64 and max(abs((t & 7) - f), abs((t >> 3) - r)) == 2 and color(b[t]) != own:
                        if not captures_only or b[t] != ".":
                            out.append(Move(i, t))
            elif u in "BRQ":
                dirs = (ORTH if u == "R" else DIAG if u == "B" else ORTH + DIAG)
                for d in dirs:
                    t = i + d
                    while edge_ok(t - d, t):
                        if color(b[t]) == own:
                            break
                        if not captures_only or b[t] != ".":
                            out.append(Move(i, t))
                        if b[t] != ".":
                            break
                        t += d
            elif u == "K":
                for d in KING:
                    t = i + d
                    if edge_ok(i, t) and color(b[t]) != own:
                        if not captures_only or b[t] != ".":
                            out.append(Move(i, t))
                if not captures_only and own == "w" and i == 4 and not self.in_check("w"):
                    if "K" in self.castle and b[5] == b[6] == "." and not self.attacked(5, "b") and not self.attacked(6, "b"):
                        out.append(Move(4, 6, "", False, True))
                    if "Q" in self.castle and b[1] == b[2] == b[3] == "." and not self.attacked(3, "b") and not self.attacked(2, "b"):
                        out.append(Move(4, 2, "", False, True))
                if not captures_only and own == "b" and i == 60 and not self.in_check("b"):
                    if "k" in self.castle and b[61] == b[62] == "." and not self.attacked(61, "w") and not self.attacked(62, "w"):
                        out.append(Move(60, 62, "", False, True))
                    if "q" in self.castle and b[57] == b[58] == b[59] == "." and not self.attacked(59, "w") and not self.attacked(58, "w"):
                        out.append(Move(60, 58, "", False, True))
        return out

    def legal_moves(self, captures_only=False):
        out = []
        side = self.side
        for m in self.pseudo(captures_only):
            old = self.make(m)
            if not self.in_check(side):
                out.append(m)
            self.unmake(old)
        return out

    def push_uci(self, text):
        for m in self.legal_moves():
            if m.uci() == text:
                self.make(m)
                return True
        return False


def pst(piece, sq, endgame):
    r, f = divmod(sq, 8)
    if piece.islower():
        r = 7 - r
    center = int(14 - (abs(f - 3.5) + abs(r - 3.5)) * 4)
    p = piece.upper()
    if p == "P":
        return r * 9 - int(abs(f - 3.5) * 3)
    if p == "N":
        return center * 3 - (0 if 1 <= r <= 6 and 1 <= f <= 6 else 8)
    if p == "B":
        return center * 2
    if p == "R":
        return r * 3
    if p == "Q":
        return center
    if p == "K":
        return center * 3 if endgame else -center * 4
    return 0


def evaluate(pos):
    b = pos.board
    material = 0
    phase = 0
    pawns = {"w": [0] * 8, "b": [0] * 8}
    bishops = {"w": 0, "b": 0}
    score = 0
    for i, p in enumerate(b):
        if p == ".":
            continue
        u = p.upper()
        side = "w" if p.isupper() else "b"
        v = VAL[u]
        material += v if side == "w" else -v
        if u in "NBRQ":
            phase += v
        if u == "P":
            pawns[side][i & 7] += 1
        if u == "B":
            bishops[side] += 1
    endgame = phase < 2600
    score += material
    if bishops["w"] >= 2:
        score += 35
    if bishops["b"] >= 2:
        score -= 35
    for i, p in enumerate(b):
        if p == ".":
            continue
        side = "w" if p.isupper() else "b"
        sign = 1 if side == "w" else -1
        u = p.upper()
        score += sign * pst(p, i, endgame)
        if u == "P":
            r, f = divmod(i, 8)
            if pawns[side][f] > 1:
                score -= sign * 10
            if (f == 0 or pawns[side][f - 1] == 0) and (f == 7 or pawns[side][f + 1] == 0):
                score -= sign * 8
            blocked = False
            passed = True
            ahead = range(r + 1, 8) if side == "w" else range(r - 1, -1, -1)
            enemy = "p" if side == "w" else "P"
            for rr in ahead:
                for ff in (f - 1, f, f + 1):
                    if 0 <= ff < 8 and b[rr * 8 + ff] == enemy:
                        passed = False
                if b[rr * 8 + f] != ".":
                    blocked = True
            if passed:
                score += sign * (18 + (r if side == "w" else 7 - r) * 10)
            if blocked:
                score -= sign * 6
    wk, bk = pos.king_sq("w"), pos.king_sq("b")
    if not endgame:
        for ks, side, sign in ((wk, "w", 1), (bk, "b", -1)):
            if ks >= 0:
                r, f = divmod(ks, 8)
                shield = 0
                pawn = "P" if side == "w" else "p"
                rr = r + (1 if side == "w" else -1)
                if 0 <= rr < 8:
                    for ff in (f - 1, f, f + 1):
                        if 0 <= ff < 8 and b[rr * 8 + ff] == pawn:
                            shield += 1
                score += sign * shield * 12
    return score if pos.side == "w" else -score


def move_score(pos, m):
    b = pos.board
    p, cap = b[m.a], b[m.b]
    s = 0
    if m.ep:
        s += 1000
    if cap != ".":
        s += 10 * VAL[cap.upper()] - VAL[p.upper()]
    if m.promo:
        s += VAL[m.promo.upper()] + 700
    if m.castle:
        s += 45
    return s


class Searcher:
    def __init__(self, pos, ms):
        self.pos = pos
        self.fast = ms <= 30
        budget = 0.003 if self.fast else max(0.001, min(ms / 1000.0 * 0.72, ms / 1000.0 - 0.004))
        self.end = time.monotonic() + budget
        self.nodes = 0
        self.stop = False

    def time_up(self):
        self.nodes += 1
        if (self.nodes & 255) == 0 and time.monotonic() >= self.end:
            self.stop = True
        return self.stop

    def qsearch(self, alpha, beta, ply=0):
        if self.time_up():
            return evaluate(self.pos)
        stand = evaluate(self.pos)
        if self.fast:
            return stand
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        if ply >= 2:
            return alpha
        moves = self.pos.legal_moves(True)
        moves.sort(key=lambda m: move_score(self.pos, m), reverse=True)
        for m in moves:
            if self.pos.board[m.b] != ".":
                gain = VAL[self.pos.board[m.b].upper()] - VAL[self.pos.board[m.a].upper()]
                if gain < -250 and not m.promo:
                    continue
            old = self.pos.make(m)
            score = -self.qsearch(-beta, -alpha, ply + 1)
            self.pos.unmake(old)
            if self.stop:
                return alpha
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def negamax(self, depth, alpha, beta, ply):
        if self.time_up():
            return evaluate(self.pos)
        if depth <= 0:
            return self.qsearch(alpha, beta)
        moves = self.pos.legal_moves()
        if not moves:
            return -MATE + ply if self.pos.in_check(self.pos.side) else 0
        moves.sort(key=lambda m: move_score(self.pos, m), reverse=True)
        best = -INF
        for m in moves:
            old = self.pos.make(m)
            score = -self.negamax(depth - 1, -beta, -alpha, ply + 1)
            self.pos.unmake(old)
            if self.stop:
                return best if best != -INF else score
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        return best

    def best(self):
        moves = self.pos.legal_moves()
        if not moves:
            return None
        moves.sort(key=lambda m: move_score(self.pos, m), reverse=True)
        best = moves[0]
        max_depth = 2 if self.fast else (1 if self.end - time.monotonic() < 0.025 else 3)
        if self.end - time.monotonic() > 0.08:
            max_depth = 4
        for depth in range(1, max_depth + 1):
            if time.monotonic() >= self.end:
                break
            local, alpha = best, -INF
            ordered = [best] + [m for m in moves if m is not best]
            for m in ordered:
                old = self.pos.make(m)
                score = -self.negamax(depth - 1, -INF, -alpha, 1)
                self.pos.unmake(old)
                if self.stop:
                    return best
                if score > alpha:
                    alpha, local = score, m
            best = local
        return best


def set_position(pos, args):
    if not args:
        return
    moves = []
    if args[0] == "startpos":
        pos.set_fen(START_FEN)
        if "moves" in args:
            moves = args[args.index("moves") + 1 :]
    elif args[0] == "fen":
        if "moves" in args:
            k = args.index("moves")
            fen = " ".join(args[1:k])
            moves = args[k + 1 :]
        else:
            fen = " ".join(args[1:7])
        pos.set_fen(fen)
    for mv in moves:
        if not pos.push_uci(mv):
            break


def main():
    pos = Position()
    for line in sys.stdin:
        parts = line.strip().split()
        if not parts:
            continue
        cmd = parts[0]
        if cmd == "uci":
            print("id name ScratchTactic")
            print("id author OpenAI")
            print("uciok")
            sys.stdout.flush()
        elif cmd == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            pos.set_fen(START_FEN)
        elif cmd == "position":
            set_position(pos, parts[1:])
        elif cmd == "go":
            ms = 20
            if "movetime" in parts:
                try:
                    ms = int(parts[parts.index("movetime") + 1])
                except Exception:
                    ms = 20
            m = Searcher(pos, ms).best()
            print("bestmove " + (m.uci() if m else "0000"))
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import sys
import time

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
INF = 10**9
PIECE_VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
FILES = "abcdefgh"


def sq_name(i):
    return FILES[i % 8] + str(i // 8 + 1)


def parse_sq(s):
    if len(s) != 2 or s[0] not in FILES or s[1] not in "12345678":
        return -1
    return (int(s[1]) - 1) * 8 + FILES.index(s[0])


def color_of(p):
    if p == ".":
        return None
    return "w" if p.isupper() else "b"


def other(c):
    return "b" if c == "w" else "w"


class Move:
    __slots__ = ("a", "b", "promo", "ep", "castle")

    def __init__(self, a, b, promo="", ep=False, castle=False):
        self.a = a
        self.b = b
        self.promo = promo
        self.ep = ep
        self.castle = castle

    def uci(self):
        return sq_name(self.a) + sq_name(self.b) + self.promo.lower()


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
        self.board = ["."] * 64
        ranks = parts[0].split("/")
        if len(ranks) != 8:
            ranks = START_FEN.split()[0].split("/")
        for r, row in enumerate(reversed(ranks)):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                elif f < 8:
                    self.board[r * 8 + f] = ch
                    f += 1
        self.side = parts[1] if len(parts) > 1 and parts[1] in ("w", "b") else "w"
        self.castle = parts[2] if len(parts) > 2 and parts[2] != "-" else "-"
        self.ep = parse_sq(parts[3]) if len(parts) > 3 and parts[3] != "-" else -1
        self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

    def king_sq(self, side):
        k = "K" if side == "w" else "k"
        try:
            return self.board.index(k)
        except ValueError:
            return -1

    def attacked(self, sq, by_side):
        b = self.board
        f = sq % 8
        if by_side == "w":
            for d in (-9, -7):
                t = sq + d
                if 0 <= t < 64 and abs(t % 8 - f) == 1 and b[t] == "P":
                    return True
        else:
            for d in (7, 9):
                t = sq + d
                if 0 <= t < 64 and abs(t % 8 - f) == 1 and b[t] == "p":
                    return True
        for d in (-17, -15, -10, -6, 6, 10, 15, 17):
            t = sq + d
            if 0 <= t < 64 and max(abs(t % 8 - f), abs(t // 8 - sq // 8)) == 2:
                if b[t] == ("N" if by_side == "w" else "n"):
                    return True
        for dirs, pieces in (((1, -1, 8, -8), "RQ"), ((9, -9, 7, -7), "BQ")):
            for d in dirs:
                t = sq + d
                while 0 <= t < 64 and abs(t % 8 - (t - d) % 8) <= 1:
                    p = b[t]
                    if p != ".":
                        if color_of(p) == by_side and p.upper() in pieces:
                            return True
                        break
                    t += d
        for d in (-9, -8, -7, -1, 1, 7, 8, 9):
            t = sq + d
            if 0 <= t < 64 and abs(t % 8 - f) <= 1:
                if b[t] == ("K" if by_side == "w" else "k"):
                    return True
        return False

    def in_check(self, side):
        k = self.king_sq(side)
        return k < 0 or self.attacked(k, other(side))

    def make(self, m):
        b = self.board
        p = b[m.a]
        cap = b[m.b]
        old = (m, p, cap, self.castle, self.ep, self.halfmove, self.fullmove)
        b[m.a] = "."
        if m.ep:
            cap_sq = m.b - 8 if self.side == "w" else m.b + 8
            old = old + (cap_sq, b[cap_sq])
            b[cap_sq] = "."
        b[m.b] = m.promo.upper() if m.promo and self.side == "w" else (m.promo.lower() if m.promo else p)
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
        self.castle = self.castle.replace("K", "") if p == "K" or m.a == 7 or m.b == 7 else self.castle
        self.castle = self.castle.replace("Q", "") if p == "K" or m.a == 0 or m.b == 0 else self.castle
        self.castle = self.castle.replace("k", "") if p == "k" or m.a == 63 or m.b == 63 else self.castle
        self.castle = self.castle.replace("q", "") if p == "k" or m.a == 56 or m.b == 56 else self.castle
        if not self.castle:
            self.castle = "-"
        self.halfmove = 0 if p.upper() == "P" or cap != "." or m.ep else self.halfmove + 1
        if self.side == "b":
            self.fullmove += 1
        self.side = other(self.side)
        return old

    def unmake(self, old):
        m, p, cap, self.castle, self.ep, self.halfmove, self.fullmove = old[:7]
        self.side = other(self.side)
        self.board[m.a] = p
        self.board[m.b] = cap
        if m.ep:
            cap_sq, cap_piece = old[7], old[8]
            self.board[cap_sq] = cap_piece
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

    def pseudo(self):
        out = []
        side = self.side
        own = side
        for i, p in enumerate(self.board):
            if color_of(p) != own:
                continue
            r, f = divmod(i, 8)
            up = p.isupper()
            if p.upper() == "P":
                step = 8 if up else -8
                start = 1 if up else 6
                promo_rank = 6 if up else 1
                one = i + step
                if 0 <= one < 64 and self.board[one] == ".":
                    if r == promo_rank:
                        for pr in "qrbn":
                            out.append(Move(i, one, pr))
                    else:
                        out.append(Move(i, one))
                        two = i + 2 * step
                        if r == start and self.board[two] == ".":
                            out.append(Move(i, two))
                for df in (-1, 1):
                    if 0 <= f + df < 8:
                        t = i + step + df
                        if 0 <= t < 64 and (color_of(self.board[t]) == other(own) or t == self.ep):
                            if r == promo_rank:
                                for pr in "qrbn":
                                    out.append(Move(i, t, pr, t == self.ep))
                            else:
                                out.append(Move(i, t, "", t == self.ep))
            elif p.upper() == "N":
                for d in (-17, -15, -10, -6, 6, 10, 15, 17):
                    t = i + d
                    if 0 <= t < 64 and max(abs(t % 8 - f), abs(t // 8 - r)) == 2 and color_of(self.board[t]) != own:
                        out.append(Move(i, t))
            elif p.upper() in "BRQ":
                dirs = []
                if p.upper() in "RQ":
                    dirs += [1, -1, 8, -8]
                if p.upper() in "BQ":
                    dirs += [9, -9, 7, -7]
                for d in dirs:
                    t = i + d
                    while 0 <= t < 64 and abs(t % 8 - (t - d) % 8) <= 1:
                        if color_of(self.board[t]) == own:
                            break
                        out.append(Move(i, t))
                        if self.board[t] != ".":
                            break
                        t += d
            elif p.upper() == "K":
                for d in (-9, -8, -7, -1, 1, 7, 8, 9):
                    t = i + d
                    if 0 <= t < 64 and abs(t % 8 - f) <= 1 and color_of(self.board[t]) != own:
                        out.append(Move(i, t))
                if own == "w" and i == 4 and not self.in_check("w"):
                    if "K" in self.castle and self.board[5] == self.board[6] == "." and not self.attacked(5, "b") and not self.attacked(6, "b"):
                        out.append(Move(4, 6, "", False, True))
                    if "Q" in self.castle and self.board[1] == self.board[2] == self.board[3] == "." and not self.attacked(3, "b") and not self.attacked(2, "b"):
                        out.append(Move(4, 2, "", False, True))
                if own == "b" and i == 60 and not self.in_check("b"):
                    if "k" in self.castle and self.board[61] == self.board[62] == "." and not self.attacked(61, "w") and not self.attacked(62, "w"):
                        out.append(Move(60, 62, "", False, True))
                    if "q" in self.castle and self.board[57] == self.board[58] == self.board[59] == "." and not self.attacked(59, "w") and not self.attacked(58, "w"):
                        out.append(Move(60, 58, "", False, True))
        return out

    def legal_moves(self):
        moves = []
        side = self.side
        for m in self.pseudo():
            old = self.make(m)
            if not self.in_check(side):
                moves.append(m)
            self.unmake(old)
        return moves

    def push_uci(self, text):
        for m in self.legal_moves():
            if m.uci() == text:
                self.make(m)
                return True
        return False


def pst(piece, sq):
    r, f = divmod(sq, 8)
    if piece.islower():
        r = 7 - r
    center = 14 - (abs(f - 3.5) + abs(r - 3.5)) * 4
    p = piece.upper()
    if p == "P":
        return r * 8 - abs(f - 3.5) * 2
    if p in "NB":
        return center * 2
    if p == "R":
        return r * 2
    if p == "Q":
        return center
    if p == "K":
        return -center if sum(1 for x in piece_pos.board if x.upper() == "Q") else center
    return 0


piece_pos = None


def evaluate(pos):
    global piece_pos
    piece_pos = pos
    score = 0
    for i, p in enumerate(pos.board):
        if p == ".":
            continue
        val = PIECE_VALUE[p.upper()] + pst(p, i)
        score += val if p.isupper() else -val
    score += 8 * (len([m for m in pos.pseudo() if pos.board[m.b] != "."]))
    return score if pos.side == "w" else -score


def move_score(pos, m):
    a, b = pos.board[m.a], pos.board[m.b]
    s = 0
    if b != ".":
        s += 10 * PIECE_VALUE[b.upper()] - PIECE_VALUE[a.upper()]
    if m.promo:
        s += PIECE_VALUE[m.promo.upper()]
    if m.castle:
        s += 40
    return s


class Searcher:
    def __init__(self, pos, end_time):
        self.pos = pos
        self.end_time = end_time
        self.nodes = 0
        self.stop = False

    def time_up(self):
        if self.nodes & 255 == 0 and time.monotonic() >= self.end_time:
            self.stop = True
        return self.stop

    def qsearch(self, alpha, beta):
        if self.time_up():
            return evaluate(self.pos)
        stand = evaluate(self.pos)
        if stand <= alpha:
            return alpha
        if stand >= beta:
            return beta
        return stand

    def negamax(self, depth, alpha, beta):
        self.nodes += 1
        if self.time_up():
            return evaluate(self.pos)
        if depth <= 0:
            return self.qsearch(alpha, beta)
        moves = self.pos.legal_moves()
        if not moves:
            return -100000 + depth if self.pos.in_check(self.pos.side) else 0
        moves.sort(key=lambda m: move_score(self.pos, m), reverse=True)
        best = -INF
        for m in moves:
            old = self.pos.make(m)
            score = -self.negamax(depth - 1, -beta, -alpha)
            self.pos.unmake(old)
            if self.stop:
                return score
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        return best

    def best(self, ms):
        moves = self.pos.legal_moves()
        if not moves:
            return None
        moves.sort(key=lambda m: move_score(self.pos, m), reverse=True)
        best = moves[0]
        budget = max(0.001, min(ms / 1000.0 - 0.006, 0.05))
        self.end_time = time.monotonic() + budget
        max_depth = 1 if ms <= 30 else 4
        for depth in range(1, max_depth + 1):
            if time.monotonic() >= self.end_time:
                break
            local_best = best
            alpha = -INF
            for m in moves:
                old = self.pos.make(m)
                score = -self.negamax(depth - 1, -INF, -alpha)
                self.pos.unmake(old)
                if self.stop:
                    return best
                if score > alpha:
                    alpha = score
                    local_best = m
            best = local_best
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
            print("id name CompactScratch")
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
            m = Searcher(pos, time.monotonic()).best(ms)
            print("bestmove " + (m.uci() if m else "0000"))
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

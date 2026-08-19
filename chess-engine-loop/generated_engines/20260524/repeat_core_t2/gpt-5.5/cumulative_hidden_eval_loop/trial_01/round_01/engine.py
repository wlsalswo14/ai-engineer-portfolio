import sys
import time


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FILES = "abcdefgh"
RANKS = "12345678"
INF = 10**9

VAL = {
    "P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0,
    "p": -100, "n": -320, "b": -330, "r": -500, "q": -900, "k": 0,
}

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
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    5, 10, 10, 10, 10, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0,
]
QUEEN_PST = [
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
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


def idx(sq):
    if len(sq) != 2 or sq[0] not in FILES or sq[1] not in RANKS:
        return -1
    return (8 - int(sq[1])) * 8 + FILES.index(sq[0])


def sq(i):
    return FILES[i % 8] + str(8 - i // 8)


def on(r, c):
    return 0 <= r < 8 and 0 <= c < 8


class Move:
    __slots__ = ("a", "b", "promo", "ep", "castle")

    def __init__(self, a, b, promo="", ep=False, castle=False):
        self.a = a
        self.b = b
        self.promo = promo
        self.ep = ep
        self.castle = castle

    def uci(self):
        return sq(self.a) + sq(self.b) + self.promo.lower()


class Pos:
    __slots__ = ("b", "side", "castles", "ep", "half", "full")

    def __init__(self, b=None, side="w", castles="", ep=-1, half=0, full=1):
        self.b = b if b is not None else ["."] * 64
        self.side = side
        self.castles = castles
        self.ep = ep
        self.half = half
        self.full = full

    @staticmethod
    def from_fen(fen):
        parts = fen.split()
        if len(parts) < 4:
            return Pos.from_fen(START_FEN)
        board = []
        for row in parts[0].split("/"):
            for ch in row:
                if ch.isdigit():
                    board.extend(["."] * int(ch))
                else:
                    board.append(ch)
        if len(board) != 64:
            return Pos.from_fen(START_FEN)
        ep = -1 if parts[3] == "-" else idx(parts[3])
        return Pos(board, parts[1] if parts[1] in ("w", "b") else "w",
                   "" if parts[2] == "-" else parts[2],
                   ep, int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0,
                   int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1)

    def own(self, p):
        return p != "." and (p.isupper() == (self.side == "w"))

    def enemy(self, p):
        return p != "." and (p.isupper() != (self.side == "w"))

    def king_index(self, side):
        k = "K" if side == "w" else "k"
        try:
            return self.b.index(k)
        except ValueError:
            return -1

    def attacked(self, target, by_side):
        brd = self.b
        tr, tc = divmod(target, 8)
        pawn = "P" if by_side == "w" else "p"
        pawn_from = 1 if by_side == "w" else -1
        for dc in (-1, 1):
            r, c = tr + pawn_from, tc + dc
            if on(r, c) and brd[r * 8 + c] == pawn:
                return True
        knight = "N" if by_side == "w" else "n"
        for dr, dc in ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)):
            r, c = tr + dr, tc + dc
            if on(r, c) and brd[r * 8 + c] == knight:
                return True
        bishop = "B" if by_side == "w" else "b"
        rook = "R" if by_side == "w" else "r"
        queen = "Q" if by_side == "w" else "q"
        for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            r, c = tr + dr, tc + dc
            while on(r, c):
                p = brd[r * 8 + c]
                if p != ".":
                    if p == bishop or p == queen:
                        return True
                    break
                r += dr
                c += dc
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            r, c = tr + dr, tc + dc
            while on(r, c):
                p = brd[r * 8 + c]
                if p != ".":
                    if p == rook or p == queen:
                        return True
                    break
                r += dr
                c += dc
        king = "K" if by_side == "w" else "k"
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr or dc:
                    r, c = tr + dr, tc + dc
                    if on(r, c) and brd[r * 8 + c] == king:
                        return True
        return False

    def in_check(self, side=None):
        side = self.side if side is None else side
        k = self.king_index(side)
        if k < 0:
            return True
        return self.attacked(k, "b" if side == "w" else "w")

    def pseudo(self):
        brd = self.b
        white = self.side == "w"
        for i, p in enumerate(brd):
            if p == "." or p.isupper() != white:
                continue
            r, c = divmod(i, 8)
            up = -1 if white else 1
            if p.upper() == "P":
                one_r = r + up
                if on(one_r, c) and brd[one_r * 8 + c] == ".":
                    to = one_r * 8 + c
                    if one_r in (0, 7):
                        for pr in "QRBN":
                            yield Move(i, to, pr if white else pr.lower())
                    else:
                        yield Move(i, to)
                        start = 6 if white else 1
                        two_r = r + 2 * up
                        if r == start and brd[two_r * 8 + c] == ".":
                            yield Move(i, two_r * 8 + c)
                for dc in (-1, 1):
                    rr, cc = r + up, c + dc
                    if not on(rr, cc):
                        continue
                    to = rr * 8 + cc
                    if self.enemy(brd[to]):
                        if rr in (0, 7):
                            for pr in "QRBN":
                                yield Move(i, to, pr if white else pr.lower())
                        else:
                            yield Move(i, to)
                    elif to == self.ep:
                        yield Move(i, to, ep=True)
            elif p.upper() == "N":
                for dr, dc in ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)):
                    rr, cc = r + dr, c + dc
                    if on(rr, cc) and not self.own(brd[rr * 8 + cc]):
                        yield Move(i, rr * 8 + cc)
            elif p.upper() in ("B", "R", "Q"):
                dirs = []
                if p.upper() in ("B", "Q"):
                    dirs += [(-1, -1), (-1, 1), (1, -1), (1, 1)]
                if p.upper() in ("R", "Q"):
                    dirs += [(-1, 0), (1, 0), (0, -1), (0, 1)]
                for dr, dc in dirs:
                    rr, cc = r + dr, c + dc
                    while on(rr, cc):
                        to = rr * 8 + cc
                        if self.own(brd[to]):
                            break
                        yield Move(i, to)
                        if self.enemy(brd[to]):
                            break
                        rr += dr
                        cc += dc
            elif p.upper() == "K":
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr or dc:
                            rr, cc = r + dr, c + dc
                            if on(rr, cc) and not self.own(brd[rr * 8 + cc]):
                                yield Move(i, rr * 8 + cc)
                if white and i == 60 and not self.in_check("w"):
                    if "K" in self.castles and brd[61] == brd[62] == "." and not self.attacked(61, "b") and not self.attacked(62, "b"):
                        yield Move(60, 62, castle=True)
                    if "Q" in self.castles and brd[59] == brd[58] == brd[57] == "." and not self.attacked(59, "b") and not self.attacked(58, "b"):
                        yield Move(60, 58, castle=True)
                if not white and i == 4 and not self.in_check("b"):
                    if "k" in self.castles and brd[5] == brd[6] == "." and not self.attacked(5, "w") and not self.attacked(6, "w"):
                        yield Move(4, 6, castle=True)
                    if "q" in self.castles and brd[3] == brd[2] == brd[1] == "." and not self.attacked(3, "w") and not self.attacked(2, "w"):
                        yield Move(4, 2, castle=True)

    def make(self, m):
        brd = self.b[:]
        p = brd[m.a]
        captured = brd[m.b]
        brd[m.a] = "."
        brd[m.b] = m.promo if m.promo else p
        if m.ep:
            brd[m.b + (8 if self.side == "w" else -8)] = "."
        if m.castle:
            if m.b == 62:
                brd[63], brd[61] = ".", "R"
            elif m.b == 58:
                brd[56], brd[59] = ".", "R"
            elif m.b == 6:
                brd[7], brd[5] = ".", "r"
            elif m.b == 2:
                brd[0], brd[3] = ".", "r"
        castles = self.castles
        for ch in castle_loss(m.a, m.b):
            castles = castles.replace(ch, "")
        ep = -1
        if p.upper() == "P" and abs(m.b - m.a) == 16:
            ep = (m.a + m.b) // 2
        half = 0 if p.upper() == "P" or captured != "." or m.ep else self.half + 1
        return Pos(brd, "b" if self.side == "w" else "w", castles, ep, half, self.full + (1 if self.side == "b" else 0))

    def legal_moves(self):
        mover = self.side
        out = []
        for m in self.pseudo():
            if not self.make(m).in_check(mover):
                out.append(m)
        return out


def castle_loss(a, b):
    lost = ""
    if a == 60:
        lost += "KQ"
    elif a == 4:
        lost += "kq"
    if a == 63 or b == 63:
        lost += "K"
    if a == 56 or b == 56:
        lost += "Q"
    if a == 7 or b == 7:
        lost += "k"
    if a == 0 or b == 0:
        lost += "q"
    return lost


def pst_value(piece, i):
    p = piece.upper()
    if p not in PST:
        return 0
    j = i if piece.isupper() else 63 - i
    v = PST[p][j]
    return v if piece.isupper() else -v


def evaluate(pos):
    score = 0
    bishops = {"w": 0, "b": 0}
    pawns = {"w": [0] * 8, "b": [0] * 8}
    for i, p in enumerate(pos.b):
        if p == ".":
            continue
        score += VAL[p] + pst_value(p, i)
        side = "w" if p.isupper() else "b"
        if p.upper() == "B":
            bishops[side] += 1
        elif p.upper() == "P":
            pawns[side][i % 8] += 1
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


def move_score(pos, m):
    victim = pos.b[m.b]
    if m.ep:
        victim = "p" if pos.side == "w" else "P"
    attacker = pos.b[m.a]
    score = 0
    if victim != ".":
        score += 10 * abs(VAL[victim]) - abs(VAL[attacker])
    if m.promo:
        score += abs(VAL[m.promo]) + 800
    if m.castle:
        score += 40
    center = m.b in (27, 28, 35, 36)
    if center:
        score += 12
    return score


class SearchTimeout(Exception):
    pass


class Engine:
    def __init__(self):
        self.pos = Pos.from_fen(START_FEN)
        self.deadline = 0.0
        self.nodes = 0

    def check_time(self):
        self.nodes += 1
        if (self.nodes & 1023) == 0 and time.monotonic() >= self.deadline:
            raise SearchTimeout

    def alphabeta(self, pos, depth, alpha, beta):
        self.check_time()
        moves = pos.legal_moves()
        if not moves:
            return -100000 + depth if pos.in_check() else 0
        if depth <= 0:
            return self.quiesce(pos, alpha, beta)
        moves.sort(key=lambda m: move_score(pos, m), reverse=True)
        best = -INF
        for m in moves:
            val = -self.alphabeta(pos.make(m), depth - 1, -beta, -alpha)
            if val > best:
                best = val
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break
        return best

    def quiesce(self, pos, alpha, beta):
        self.check_time()
        stand = evaluate(pos)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        caps = [m for m in pos.legal_moves() if pos.b[m.b] != "." or m.ep or m.promo]
        caps.sort(key=lambda m: move_score(pos, m), reverse=True)
        for m in caps[:24]:
            val = -self.quiesce(pos.make(m), -beta, -alpha)
            if val >= beta:
                return beta
            if val > alpha:
                alpha = val
        return alpha

    def bestmove(self, movetime_ms):
        moves = self.pos.legal_moves()
        if not moves:
            return "0000"
        moves.sort(key=lambda m: move_score(self.pos, m), reverse=True)
        best = moves[0]
        budget = max(0.005, min(5.0, movetime_ms / 1000.0))
        self.deadline = time.monotonic() + budget * 0.80
        self.nodes = 0
        max_depth = 1 if movetime_ms < 15 else 5
        try:
            for depth in range(1, max_depth + 1):
                local_best = best
                local_score = -INF
                alpha = -INF
                for m in moves:
                    score = -self.alphabeta(self.pos.make(m), depth - 1, -INF, -alpha)
                    if score > local_score:
                        local_score = score
                        local_best = m
                    if score > alpha:
                        alpha = score
                    if time.monotonic() >= self.deadline:
                        raise SearchTimeout
                best = local_best
                moves.sort(key=lambda m: (m.uci() == best.uci(), move_score(self.pos, m)), reverse=True)
        except SearchTimeout:
            pass
        return best.uci()

    def apply_uci_move(self, token):
        if len(token) < 4:
            return
        for m in self.pos.legal_moves():
            if m.uci() == token:
                self.pos = self.pos.make(m)
                return

    def set_position(self, args):
        try:
            if not args:
                return
            moves_at = args.index("moves") if "moves" in args else len(args)
            if args[0] == "startpos":
                self.pos = Pos.from_fen(START_FEN)
            elif args[0] == "fen" and moves_at >= 7:
                self.pos = Pos.from_fen(" ".join(args[1:7]))
            else:
                return
            for mv in args[moves_at + 1:]:
                self.apply_uci_move(mv)
        except Exception:
            self.pos = Pos.from_fen(START_FEN)


def main():
    eng = Engine()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        if cmd == "uci":
            print("id name ScratchSimplePy")
            print("id author OpenAI")
            print("uciok")
            sys.stdout.flush()
        elif cmd == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            eng.pos = Pos.from_fen(START_FEN)
        elif cmd == "position":
            eng.set_position(parts[1:])
        elif cmd == "go":
            ms = 20
            if "movetime" in parts:
                try:
                    ms = int(parts[parts.index("movetime") + 1])
                except Exception:
                    ms = 20
            print("bestmove " + eng.bestmove(ms))
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

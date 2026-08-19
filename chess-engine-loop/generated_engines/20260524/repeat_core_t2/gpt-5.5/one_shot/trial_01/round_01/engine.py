import sys
import time

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FILES = "abcdefgh"
PIECE_VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
MATE = 100000

N_DIRS = (-17, -15, 15, 17)
B_DIRS = (-9, -7, 7, 9)
R_DIRS = (-8, -1, 1, 8)
Q_DIRS = B_DIRS + R_DIRS
K_DIRS = (-9, -8, -7, -1, 1, 7, 8, 9)

PST = {
    "P": [0, 0, 0, 0, 0, 0, 0, 0,
          50, 50, 50, 50, 50, 50, 50, 50,
          10, 10, 20, 30, 30, 20, 10, 10,
          5, 5, 10, 25, 25, 10, 5, 5,
          0, 0, 0, 20, 20, 0, 0, 0,
          5, -5, -10, 0, 0, -10, -5, 5,
          5, 10, 10, -20, -20, 10, 10, 5,
          0, 0, 0, 0, 0, 0, 0, 0],
    "N": [-50, -40, -30, -30, -30, -30, -40, -50,
          -40, -20, 0, 5, 5, 0, -20, -40,
          -30, 5, 10, 15, 15, 10, 5, -30,
          -30, 0, 15, 20, 20, 15, 0, -30,
          -30, 5, 15, 20, 20, 15, 5, -30,
          -30, 0, 10, 15, 15, 10, 0, -30,
          -40, -20, 0, 0, 0, 0, -20, -40,
          -50, -40, -30, -30, -30, -30, -40, -50],
    "B": [-20, -10, -10, -10, -10, -10, -10, -20,
          -10, 5, 0, 0, 0, 0, 5, -10,
          -10, 10, 10, 10, 10, 10, 10, -10,
          -10, 0, 10, 10, 10, 10, 0, -10,
          -10, 5, 5, 10, 10, 5, 5, -10,
          -10, 0, 5, 10, 10, 5, 0, -10,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -20, -10, -10, -10, -10, -10, -10, -20],
    "R": [0, 0, 5, 10, 10, 5, 0, 0,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          5, 10, 10, 10, 10, 10, 10, 5,
          0, 0, 0, 0, 0, 0, 0, 0],
    "Q": [-20, -10, -10, -5, -5, -10, -10, -20,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -10, 0, 5, 5, 5, 5, 0, -10,
          -5, 0, 5, 5, 5, 5, 0, -5,
          0, 0, 5, 5, 5, 5, 0, -5,
          -10, 5, 5, 5, 5, 5, 0, -10,
          -10, 0, 5, 0, 0, 0, 0, -10,
          -20, -10, -10, -5, -5, -10, -10, -20],
    "K": [20, 30, 10, 0, 0, 10, 30, 20,
          20, 20, 0, 0, 0, 0, 20, 20,
          -10, -20, -20, -20, -20, -20, -20, -10,
          -20, -30, -30, -40, -40, -30, -30, -20,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30],
}


def sq(s):
    return (8 - int(s[1])) * 8 + FILES.index(s[0])


def name(i):
    return FILES[i & 7] + str(8 - (i >> 3))


def same_line(a, b, d):
    if not 0 <= b < 64:
        return False
    af, bf = a & 7, b & 7
    if d in (-1, 1):
        return (a >> 3) == (b >> 3)
    if d in (-9, 7):
        return bf == af - 1
    if d in (-7, 9):
        return bf == af + 1
    return True


class Position:
    def __init__(self):
        self.set_fen(START_FEN)

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            parts = START_FEN.split()
        board = []
        for row in parts[0].split("/"):
            for ch in row:
                if ch.isdigit():
                    board.extend("." * int(ch))
                else:
                    board.append(ch)
        self.b = board[:64] if len(board) == 64 else list(Position().b)
        self.turn = parts[1] if parts[1] in ("w", "b") else "w"
        self.castle = parts[2] if parts[2] != "-" else ""
        self.ep = -1 if parts[3] == "-" else sq(parts[3])
        self.half = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.full = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

    def copy(self):
        p = Position.__new__(Position)
        p.b = self.b[:]
        p.turn = self.turn
        p.castle = self.castle
        p.ep = self.ep
        p.half = self.half
        p.full = self.full
        return p

    def king(self, color):
        k = "K" if color == "w" else "k"
        return self.b.index(k) if k in self.b else -1

    def attacked(self, target, by_color):
        by_white = by_color == "w"
        pawns = (7, 9) if by_white else (-7, -9)
        pawn = "P" if by_white else "p"
        for d in pawns:
            s = target + d
            if 0 <= s < 64 and same_line(target, s, d) and self.b[s] == pawn:
                return True
        knight = "N" if by_white else "n"
        for d in N_DIRS:
            s = target + d
            if 0 <= s < 64 and abs((s & 7) - (target & 7)) in (1, 2) and self.b[s] == knight:
                return True
        king = "K" if by_white else "k"
        for d in K_DIRS:
            s = target + d
            if 0 <= s < 64 and same_line(target, s, d) and self.b[s] == king:
                return True
        for d in B_DIRS:
            s = target + d
            while 0 <= s < 64 and same_line(s - d, s, d):
                pc = self.b[s]
                if pc != ".":
                    if pc.isupper() == by_white and pc.upper() in ("B", "Q"):
                        return True
                    break
                s += d
        for d in R_DIRS:
            s = target + d
            while 0 <= s < 64 and same_line(s - d, s, d):
                pc = self.b[s]
                if pc != ".":
                    if pc.isupper() == by_white and pc.upper() in ("R", "Q"):
                        return True
                    break
                s += d
        return False

    def in_check(self, color):
        k = self.king(color)
        return k < 0 or self.attacked(k, "b" if color == "w" else "w")

    def pseudo(self):
        moves = []
        white = self.turn == "w"
        for i, pc in enumerate(self.b):
            if pc == "." or pc.isupper() != white:
                continue
            up = pc.upper()
            if up == "P":
                step = -8 if white else 8
                start_rank = 6 if white else 1
                promo_rank = 0 if white else 7
                one = i + step
                if 0 <= one < 64 and self.b[one] == ".":
                    if one >> 3 == promo_rank:
                        for pr in "qrbn":
                            moves.append((i, one, pr))
                    else:
                        moves.append((i, one, ""))
                        two = i + 2 * step
                        if i >> 3 == start_rank and self.b[two] == ".":
                            moves.append((i, two, ""))
                for d in (step - 1, step + 1):
                    to = i + d
                    if not (0 <= to < 64 and abs((to & 7) - (i & 7)) == 1):
                        continue
                    tgt = self.b[to]
                    if tgt != "." and tgt.isupper() != white or to == self.ep:
                        if to >> 3 == promo_rank:
                            for pr in "qrbn":
                                moves.append((i, to, pr))
                        else:
                            moves.append((i, to, ""))
            elif up == "N":
                for d in N_DIRS:
                    to = i + d
                    if 0 <= to < 64 and abs((to & 7) - (i & 7)) in (1, 2):
                        tgt = self.b[to]
                        if tgt == "." or tgt.isupper() != white:
                            moves.append((i, to, ""))
            elif up in ("B", "R", "Q"):
                dirs = B_DIRS if up == "B" else R_DIRS if up == "R" else Q_DIRS
                for d in dirs:
                    to = i + d
                    while 0 <= to < 64 and same_line(to - d, to, d):
                        tgt = self.b[to]
                        if tgt == ".":
                            moves.append((i, to, ""))
                        else:
                            if tgt.isupper() != white:
                                moves.append((i, to, ""))
                            break
                        to += d
            elif up == "K":
                for d in K_DIRS:
                    to = i + d
                    if 0 <= to < 64 and same_line(i, to, d):
                        tgt = self.b[to]
                        if tgt == "." or tgt.isupper() != white:
                            moves.append((i, to, ""))
                if white and i == 60 and not self.in_check("w"):
                    if "K" in self.castle and self.b[61] == self.b[62] == ".":
                        if not self.attacked(61, "b") and not self.attacked(62, "b"):
                            moves.append((60, 62, ""))
                    if "Q" in self.castle and self.b[59] == self.b[58] == self.b[57] == ".":
                        if not self.attacked(59, "b") and not self.attacked(58, "b"):
                            moves.append((60, 58, ""))
                if not white and i == 4 and not self.in_check("b"):
                    if "k" in self.castle and self.b[5] == self.b[6] == ".":
                        if not self.attacked(5, "w") and not self.attacked(6, "w"):
                            moves.append((4, 6, ""))
                    if "q" in self.castle and self.b[3] == self.b[2] == self.b[1] == ".":
                        if not self.attacked(3, "w") and not self.attacked(2, "w"):
                            moves.append((4, 2, ""))
        return moves

    def make(self, m):
        fr, to, promo = m
        p = self.copy()
        pc = p.b[fr]
        cap = p.b[to]
        p.b[fr] = "."
        if pc.upper() == "P" and to == self.ep and cap == ".":
            p.b[to + (8 if pc.isupper() else -8)] = "."
        p.b[to] = promo.upper() if pc.isupper() and promo else promo if promo else pc
        if pc == "K" and fr == 60:
            p.castle = p.castle.replace("K", "").replace("Q", "")
            if to == 62:
                p.b[63], p.b[61] = ".", "R"
            elif to == 58:
                p.b[56], p.b[59] = ".", "R"
        elif pc == "k" and fr == 4:
            p.castle = p.castle.replace("k", "").replace("q", "")
            if to == 6:
                p.b[7], p.b[5] = ".", "r"
            elif to == 2:
                p.b[0], p.b[3] = ".", "r"
        if pc == "R":
            if fr == 63:
                p.castle = p.castle.replace("K", "")
            elif fr == 56:
                p.castle = p.castle.replace("Q", "")
        elif pc == "r":
            if fr == 7:
                p.castle = p.castle.replace("k", "")
            elif fr == 0:
                p.castle = p.castle.replace("q", "")
        if cap == "R":
            if to == 63:
                p.castle = p.castle.replace("K", "")
            elif to == 56:
                p.castle = p.castle.replace("Q", "")
        elif cap == "r":
            if to == 7:
                p.castle = p.castle.replace("k", "")
            elif to == 0:
                p.castle = p.castle.replace("q", "")
        p.ep = -1
        if pc.upper() == "P" and abs(to - fr) == 16:
            p.ep = (to + fr) // 2
        p.turn = "b" if self.turn == "w" else "w"
        p.half = 0 if pc.upper() == "P" or cap != "." else p.half + 1
        if p.turn == "w":
            p.full += 1
        return p

    def legal_moves(self):
        color = self.turn
        out = []
        for m in self.pseudo():
            p = self.make(m)
            if not p.in_check(color):
                out.append(m)
        return out


def move_to_uci(m):
    return name(m[0]) + name(m[1]) + m[2]


def parse_uci_move(pos, text):
    if len(text) < 4:
        return None
    try:
        fr, to = sq(text[:2]), sq(text[2:4])
    except Exception:
        return None
    pr = text[4].lower() if len(text) > 4 else ""
    for m in pos.legal_moves():
        if m == (fr, to, pr):
            return m
    return None


def evaluate(pos):
    score = 0
    bishops = {"w": 0, "b": 0}
    for i, pc in enumerate(pos.b):
        if pc == ".":
            continue
        up = pc.upper()
        val = PIECE_VALUE[up]
        pst_i = i if pc.isupper() else 63 - i
        val += PST.get(up, [0] * 64)[pst_i]
        if up == "B":
            bishops["w" if pc.isupper() else "b"] += 1
        score += val if pc.isupper() else -val
    if bishops["w"] >= 2:
        score += 35
    if bishops["b"] >= 2:
        score -= 35
    return score if pos.turn == "w" else -score


def ordered(pos, moves):
    def key(m):
        fr, to, pr = m
        pc = pos.b[fr].upper()
        cap = pos.b[to]
        v = 0
        if cap != ".":
            v += 10 * PIECE_VALUE[cap.upper()] - PIECE_VALUE[pc]
        if pr:
            v += PIECE_VALUE[pr.upper()]
        if pc in ("P", "N", "B") and 16 <= to <= 47:
            v += 5
        return v
    return sorted(moves, key=key, reverse=True)


def qsearch(pos, alpha, beta, deadline):
    stand = evaluate(pos)
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    if time.time() >= deadline:
        return alpha
    caps = [m for m in pos.legal_moves() if pos.b[m[1]] != "." or m[2]]
    for m in ordered(pos, caps):
        score = -qsearch(pos.make(m), -beta, -alpha, deadline)
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
    return alpha


def search(pos, depth, alpha, beta, deadline):
    if time.time() >= deadline:
        raise TimeoutError
    moves = pos.legal_moves()
    if not moves:
        return -MATE + depth if pos.in_check(pos.turn) else 0
    if depth <= 0:
        return qsearch(pos, alpha, beta, deadline)
    best = -MATE
    for m in ordered(pos, moves):
        score = -search(pos.make(m), depth - 1, -beta, -alpha, deadline)
        if score > best:
            best = score
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
    return best


def best_move(pos, ms):
    moves = pos.legal_moves()
    if not moves:
        return "0000"
    deadline = time.time() + max(0.005, (ms - 5) / 1000.0)
    best = ordered(pos, moves)[0]
    max_depth = 5 if ms >= 80 else 3
    depth = 1
    while depth <= max_depth:
        try:
            local_best = best
            alpha = -MATE
            for m in ordered(pos, moves):
                score = -search(pos.make(m), depth - 1, -MATE, -alpha, deadline)
                if score > alpha:
                    alpha = score
                    local_best = m
            best = local_best
            depth += 1
        except TimeoutError:
            break
    return move_to_uci(best)


def set_position(pos, args):
    if not args:
        return pos
    try:
        if args[0] == "startpos":
            pos.set_fen(START_FEN)
            rest = args[1:]
        elif args[0] == "fen" and len(args) >= 7:
            pos.set_fen(" ".join(args[1:7]))
            rest = args[7:]
        else:
            return pos
        if rest and rest[0] == "moves":
            for mv in rest[1:]:
                m = parse_uci_move(pos, mv)
                if m is None:
                    break
                pos = pos.make(m)
    except Exception:
        pass
    return pos


def main():
    pos = Position()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        if cmd == "uci":
            print("id name ScratchLegalPy")
            print("id author OpenAI")
            print("uciok")
            sys.stdout.flush()
        elif cmd == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            pos = Position()
        elif cmd == "position":
            pos = set_position(pos, parts[1:])
        elif cmd == "go":
            ms = 20
            if "movetime" in parts:
                try:
                    ms = int(parts[parts.index("movetime") + 1])
                except Exception:
                    pass
            print("bestmove " + best_move(pos, ms))
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

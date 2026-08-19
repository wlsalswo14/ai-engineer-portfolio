import sys
import time

FILES = "abcdefgh"
RANKS = "12345678"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PIECE_VALUE = {
    "P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0,
    "p": -100, "n": -320, "b": -330, "r": -500, "q": -900, "k": 0,
}
KNIGHT = (17, 15, 10, 6, -17, -15, -10, -6)
KING = (9, 8, 7, 1, -1, -7, -8, -9)
BISHOP = (9, 7, -7, -9)
ROOK = (8, -8, 1, -1)


def sq(file_i, rank_i):
    return rank_i * 8 + file_i


def on_board(s):
    return 0 <= s < 64


def same_row(a, b):
    return a // 8 == b // 8


def square_name(s):
    return FILES[s % 8] + RANKS[s // 8]


def parse_square(t):
    if len(t) != 2 or t[0] not in FILES or t[1] not in RANKS:
        return -1
    return sq(FILES.index(t[0]), RANKS.index(t[1]))


class Move:
    __slots__ = ("frm", "to", "promo", "ep", "castle")

    def __init__(self, frm, to, promo="", ep=False, castle=False):
        self.frm = frm
        self.to = to
        self.promo = promo
        self.ep = ep
        self.castle = castle

    def uci(self):
        return square_name(self.frm) + square_name(self.to) + self.promo.lower()


class Position:
    __slots__ = ("b", "white", "castle", "ep", "halfmove", "fullmove")

    def __init__(self):
        self.b = ["."] * 64
        self.white = True
        self.castle = ""
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1

    def clone(self):
        p = Position()
        p.b = self.b[:]
        p.white = self.white
        p.castle = self.castle
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        return p

    def set_fen(self, fen):
        try:
            parts = fen.strip().split()
            if len(parts) < 4:
                raise ValueError
            board, turn, castle, ep = parts[:4]
            self.b = ["."] * 64
            ranks = board.split("/")
            if len(ranks) != 8:
                raise ValueError
            for fen_rank, row in enumerate(ranks):
                file_i = 0
                rank_i = 7 - fen_rank
                for ch in row:
                    if ch.isdigit():
                        file_i += int(ch)
                    elif ch in "PNBRQKpnbrqk" and file_i < 8:
                        self.b[sq(file_i, rank_i)] = ch
                        file_i += 1
                    else:
                        raise ValueError
                if file_i != 8:
                    raise ValueError
            self.white = turn != "b"
            self.castle = "" if castle == "-" else "".join(c for c in castle if c in "KQkq")
            self.ep = parse_square(ep) if ep != "-" else -1
            self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
        except Exception:
            self.set_fen(START_FEN)

    def king_square(self, white):
        k = "K" if white else "k"
        for i, p in enumerate(self.b):
            if p == k:
                return i
        return -1

    def attacked(self, target, by_white):
        pawns = (-7, -9) if by_white else (7, 9)
        for d in pawns:
            s = target + d
            if on_board(s) and abs((s % 8) - (target % 8)) == 1:
                if self.b[s] == ("P" if by_white else "p"):
                    return True
        for d in KNIGHT:
            s = target + d
            if on_board(s) and max(abs((s % 8) - (target % 8)), abs((s // 8) - (target // 8))) <= 2:
                if self.b[s] == ("N" if by_white else "n"):
                    return True
        for dirs, pieces in ((BISHOP, "BQ" if by_white else "bq"), (ROOK, "RQ" if by_white else "rq")):
            for d in dirs:
                s = target + d
                while on_board(s) and (d not in (1, -1) or same_row(s, s - d)) and (d not in (9, -7) or (s % 8) > ((s - d) % 8)) and (d not in (7, -9) or (s % 8) < ((s - d) % 8)):
                    p = self.b[s]
                    if p != ".":
                        if p in pieces:
                            return True
                        break
                    s += d
        for d in KING:
            s = target + d
            if on_board(s) and max(abs((s % 8) - (target % 8)), abs((s // 8) - (target // 8))) == 1:
                if self.b[s] == ("K" if by_white else "k"):
                    return True
        return False

    def in_check(self, white):
        k = self.king_square(white)
        return k < 0 or self.attacked(k, not white)

    def pseudo_moves(self):
        side_white = self.white
        own = str.isupper if side_white else str.islower
        enemy = str.islower if side_white else str.isupper
        moves = []
        for i, p in enumerate(self.b):
            if p == "." or not own(p):
                continue
            f, r = i % 8, i // 8
            up = 8 if side_white else -8
            if p in "Pp":
                one = i + up
                start_rank = 1 if side_white else 6
                promo_rank = 6 if side_white else 1
                if on_board(one) and self.b[one] == ".":
                    if r == promo_rank:
                        for pr in "qrbn":
                            moves.append(Move(i, one, pr))
                    else:
                        moves.append(Move(i, one))
                        two = i + 2 * up
                        if r == start_rank and self.b[two] == ".":
                            moves.append(Move(i, two))
                for df in (-1, 1):
                    if 0 <= f + df < 8:
                        to = i + up + df
                        if on_board(to) and ((self.b[to] != "." and enemy(self.b[to])) or to == self.ep):
                            if r == promo_rank:
                                for pr in "qrbn":
                                    moves.append(Move(i, to, pr, to == self.ep))
                            else:
                                moves.append(Move(i, to, "", to == self.ep))
            elif p in "Nn":
                for d in KNIGHT:
                    to = i + d
                    if on_board(to) and max(abs((to % 8) - f), abs((to // 8) - r)) <= 2 and not (self.b[to] != "." and own(self.b[to])):
                        moves.append(Move(i, to))
            elif p in "BbRrQq":
                dirs = []
                if p in "BbQq":
                    dirs += BISHOP
                if p in "RrQq":
                    dirs += ROOK
                for d in dirs:
                    to = i + d
                    while on_board(to) and (d not in (1, -1) or same_row(to, to - d)) and (d not in (9, -7) or (to % 8) > ((to - d) % 8)) and (d not in (7, -9) or (to % 8) < ((to - d) % 8)):
                        if self.b[to] == ".":
                            moves.append(Move(i, to))
                        else:
                            if enemy(self.b[to]):
                                moves.append(Move(i, to))
                            break
                        to += d
            elif p in "Kk":
                for d in KING:
                    to = i + d
                    if on_board(to) and max(abs((to % 8) - f), abs((to // 8) - r)) == 1 and not (self.b[to] != "." and own(self.b[to])):
                        moves.append(Move(i, to))
                if side_white and i == 4 and not self.in_check(True):
                    if "K" in self.castle and self.b[5] == self.b[6] == "." and not self.attacked(5, False) and not self.attacked(6, False):
                        moves.append(Move(4, 6, "", False, True))
                    if "Q" in self.castle and self.b[1] == self.b[2] == self.b[3] == "." and not self.attacked(3, False) and not self.attacked(2, False):
                        moves.append(Move(4, 2, "", False, True))
                if (not side_white) and i == 60 and not self.in_check(False):
                    if "k" in self.castle and self.b[61] == self.b[62] == "." and not self.attacked(61, True) and not self.attacked(62, True):
                        moves.append(Move(60, 62, "", False, True))
                    if "q" in self.castle and self.b[57] == self.b[58] == self.b[59] == "." and not self.attacked(59, True) and not self.attacked(58, True):
                        moves.append(Move(60, 58, "", False, True))
        return moves

    def make(self, m):
        p = self.clone()
        piece = p.b[m.frm]
        captured = p.b[m.to]
        p.b[m.frm] = "."
        if m.ep:
            p.b[m.to + (-8 if piece == "P" else 8)] = "."
        if m.castle:
            if m.to == 6:
                p.b[5], p.b[7] = "R", "."
            elif m.to == 2:
                p.b[3], p.b[0] = "R", "."
            elif m.to == 62:
                p.b[61], p.b[63] = "r", "."
            elif m.to == 58:
                p.b[59], p.b[56] = "r", "."
        p.b[m.to] = m.promo.upper() if (m.promo and piece.isupper()) else (m.promo.lower() if m.promo else piece)
        for c, squares in (("K", (4, 7)), ("Q", (4, 0)), ("k", (60, 63)), ("q", (60, 56))):
            if piece.lower() == "k" and ((piece.isupper() and c in "KQ") or (piece.islower() and c in "kq")):
                p.castle = p.castle.replace(c, "")
            if m.frm in squares or m.to in squares:
                p.castle = p.castle.replace(c, "")
        p.ep = -1
        if piece in "Pp" and abs(m.to - m.frm) == 16:
            p.ep = (m.to + m.frm) // 2
        p.halfmove = 0 if piece in "Pp" or captured != "." or m.ep else p.halfmove + 1
        if not p.white:
            p.fullmove += 1
        p.white = not p.white
        return p

    def legal_moves(self):
        res = []
        side = self.white
        for m in self.pseudo_moves():
            np = self.make(m)
            if not np.in_check(side):
                res.append(m)
        return res


def evaluate(pos):
    score = 0
    bishops_w = bishops_b = 0
    for i, p in enumerate(pos.b):
        if p == ".":
            continue
        v = PIECE_VALUE[p]
        f, r = i % 8, i // 8
        center = 6 - (abs(f - 3) + abs(f - 4) + abs(r - 3) + abs(r - 4))
        if p.upper() in "NB":
            v += (center * 5) if p.isupper() else -(center * 5)
        if p.upper() == "P":
            adv = r if p.isupper() else 7 - r
            v += adv * (8 if p.isupper() else -8)
        if p == "B":
            bishops_w += 1
        elif p == "b":
            bishops_b += 1
        score += v
    if bishops_w >= 2:
        score += 30
    if bishops_b >= 2:
        score -= 30
    if pos.in_check(pos.white):
        score += -25 if pos.white else 25
    return score


def move_score(pos, m):
    victim = pos.b[m.to]
    attacker = pos.b[m.frm]
    score = 0
    if victim != ".":
        score += abs(PIECE_VALUE[victim]) * 10 - abs(PIECE_VALUE[attacker])
    if m.promo:
        score += abs(PIECE_VALUE[m.promo.upper()]) + 500
    if m.castle:
        score += 50
    return score


def search(pos, depth, alpha, beta, end_time):
    if time.time() >= end_time:
        raise TimeoutError
    moves = pos.legal_moves()
    if not moves:
        if pos.in_check(pos.white):
            return -100000 + (4 - depth) if pos.white else 100000 - (4 - depth)
        return 0
    if depth <= 0:
        return evaluate(pos)
    moves.sort(key=lambda m: move_score(pos, m), reverse=True)
    if pos.white:
        best = -1000000
        for m in moves:
            best = max(best, search(pos.make(m), depth - 1, alpha, beta, end_time))
            alpha = max(alpha, best)
            if alpha >= beta:
                break
        return best
    best = 1000000
    for m in moves:
        best = min(best, search(pos.make(m), depth - 1, alpha, beta, end_time))
        beta = min(beta, best)
        if alpha >= beta:
            break
    return best


def choose_move(pos, movetime_ms):
    moves = pos.legal_moves()
    if not moves:
        return "0000"
    moves.sort(key=lambda m: move_score(pos, m), reverse=True)
    best = moves[0]
    budget = max(0.005, min(1.0, movetime_ms / 1000.0) * 0.80)
    end_time = time.time() + budget
    if movetime_ms < 35:
        max_depth = 1
    elif movetime_ms < 100:
        max_depth = 2
    else:
        max_depth = 4
    for depth in range(1, max_depth + 1):
        if time.time() >= end_time:
            break
        try:
            local_best = best
            local_score = -1000000 if pos.white else 1000000
            ordered = sorted(moves, key=lambda m: move_score(pos, m), reverse=True)
            for m in ordered:
                if time.time() >= end_time:
                    raise TimeoutError
                sc = search(pos.make(m), depth - 1, -1000000, 1000000, end_time)
                if (pos.white and sc > local_score) or ((not pos.white) and sc < local_score):
                    local_score = sc
                    local_best = m
            best = local_best
        except TimeoutError:
            break
        except Exception:
            break
    return best.uci()


def apply_uci_move(pos, text):
    if len(text) < 4:
        return pos
    for m in pos.legal_moves():
        if m.uci() == text[:5].lower():
            return pos.make(m)
    frm, to = parse_square(text[:2]), parse_square(text[2:4])
    if frm >= 0 and to >= 0 and pos.b[frm] != ".":
        return pos.make(Move(frm, to, text[4:5].lower()))
    return pos


def set_position(pos, args):
    if not args:
        return pos
    moves_at = args.index("moves") if "moves" in args else len(args)
    if args[0] == "startpos":
        pos.set_fen(START_FEN)
    elif args[0] == "fen" and moves_at >= 7:
        pos.set_fen(" ".join(args[1:7]))
    for mv in args[moves_at + 1:]:
        pos = apply_uci_move(pos, mv)
    return pos


def main():
    pos = Position()
    pos.set_fen(START_FEN)
    for line in sys.stdin:
        parts = line.strip().split()
        if not parts:
            continue
        cmd = parts[0]
        if cmd == "uci":
            print("id name ScratchPy")
            print("id author Codex")
            print("uciok", flush=True)
        elif cmd == "isready":
            print("readyok", flush=True)
        elif cmd == "ucinewgame":
            pos.set_fen(START_FEN)
        elif cmd == "position":
            pos = set_position(pos, parts[1:])
        elif cmd == "go":
            mt = 20
            if "movetime" in parts:
                try:
                    mt = int(parts[parts.index("movetime") + 1])
                except Exception:
                    mt = 20
            print("bestmove " + choose_move(pos, mt), flush=True)
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

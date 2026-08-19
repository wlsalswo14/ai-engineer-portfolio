#!/usr/bin/env python3
import sys
import time

WHITE, BLACK = 0, 1
INF = 10**9
MATE = 100000
FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}

KNIGHT = (-17, -15, -10, -6, 6, 10, 15, 17)
BISHOP = (-9, -7, 7, 9)
ROOK = (-8, -1, 1, 8)
KING = (-9, -8, -7, -1, 1, 7, 8, 9)


def color_of(piece):
    return WHITE if piece.isupper() else BLACK


def sq_name(sq):
    return FILES[sq % 8] + str(8 - sq // 8)


def parse_sq(text):
    if len(text) != 2 or text[0] not in FILES or text[1] not in "12345678":
        return None
    return (8 - int(text[1])) * 8 + FILES.index(text[0])


def same_rank(a, b):
    return a // 8 == b // 8


def step_ok(src, dst, delta):
    if not 0 <= dst < 64:
        return False
    dr = abs(dst // 8 - src // 8)
    df = abs(dst % 8 - src % 8)
    if abs(delta) in (6, 10, 15, 17):
        return (dr, df) in ((1, 2), (2, 1))
    if abs(delta) in (7, 9):
        return dr == 1 and df == 1
    if abs(delta) == 1:
        return dr == 0 and df == 1
    if abs(delta) == 8:
        return dr == 1 and df == 0
    return True


class Move:
    __slots__ = ("src", "dst", "promo", "ep", "castle")

    def __init__(self, src, dst, promo="", ep=False, castle=False):
        self.src = src
        self.dst = dst
        self.promo = promo
        self.ep = ep
        self.castle = castle

    def uci(self):
        return sq_name(self.src) + sq_name(self.dst) + self.promo.lower()


class Board:
    def __init__(self):
        self.b = ["."] * 64
        self.side = WHITE
        self.castle = ""
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.set_fen(START_FEN)

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            parts = START_FEN.split()
        self.b = []
        for row in parts[0].split("/"):
            for ch in row:
                if ch.isdigit():
                    self.b.extend(["."] * int(ch))
                else:
                    self.b.append(ch)
        if len(self.b) != 64:
            self.b = Board().b
        self.side = WHITE if parts[1] == "w" else BLACK
        self.castle = "" if parts[2] == "-" else parts[2]
        self.ep = None if parts[3] == "-" else parse_sq(parts[3])
        self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

    def king_sq(self, side):
        k = "K" if side == WHITE else "k"
        try:
            return self.b.index(k)
        except ValueError:
            return -1

    def attacked(self, sq, by_side):
        pawn_dirs = (7, 9) if by_side == WHITE else (-7, -9)
        pawn = "P" if by_side == WHITE else "p"
        for d in pawn_dirs:
            s = sq + d
            if 0 <= s < 64 and step_ok(s, sq, -d) and self.b[s] == pawn:
                return True
        for d in KNIGHT:
            s = sq + d
            if 0 <= s < 64 and step_ok(sq, s, d) and self.b[s] == ("N" if by_side == WHITE else "n"):
                return True
        for d in BISHOP:
            s = sq + d
            while 0 <= s < 64 and step_ok(s - d, s, d):
                p = self.b[s]
                if p != ".":
                    return color_of(p) == by_side and p.upper() in ("B", "Q")
                s += d
        for d in ROOK:
            s = sq + d
            while 0 <= s < 64 and step_ok(s - d, s, d):
                p = self.b[s]
                if p != ".":
                    return color_of(p) == by_side and p.upper() in ("R", "Q")
                s += d
        king = "K" if by_side == WHITE else "k"
        for d in KING:
            s = sq + d
            if 0 <= s < 64 and step_ok(sq, s, d) and self.b[s] == king:
                return True
        return False

    def in_check(self, side):
        k = self.king_sq(side)
        return k < 0 or self.attacked(k, 1 - side)

    def pseudo_moves(self):
        side = self.side
        for i, p in enumerate(self.b):
            if p == "." or color_of(p) != side:
                continue
            up = p.upper()
            if up == "P":
                yield from self.pawn_moves(i, p)
            elif up == "N":
                yield from self.jump_moves(i, p, KNIGHT)
            elif up == "B":
                yield from self.slide_moves(i, p, BISHOP)
            elif up == "R":
                yield from self.slide_moves(i, p, ROOK)
            elif up == "Q":
                yield from self.slide_moves(i, p, BISHOP + ROOK)
            elif up == "K":
                yield from self.jump_moves(i, p, KING)
                yield from self.castle_moves(i, p)

    def pawn_moves(self, i, p):
        side = color_of(p)
        fwd = -8 if side == WHITE else 8
        start_rank = 6 if side == WHITE else 1
        promo_rank = 0 if side == WHITE else 7
        one = i + fwd
        if 0 <= one < 64 and self.b[one] == ".":
            if one // 8 == promo_rank:
                for pr in "qrbn":
                    yield Move(i, one, pr)
            else:
                yield Move(i, one)
                two = i + 2 * fwd
                if i // 8 == start_rank and self.b[two] == ".":
                    yield Move(i, two)
        for d in (fwd - 1, fwd + 1):
            dst = i + d
            if not (0 <= dst < 64 and step_ok(i, dst, d)):
                continue
            target = self.b[dst]
            if target != "." and color_of(target) != side:
                if dst // 8 == promo_rank:
                    for pr in "qrbn":
                        yield Move(i, dst, pr)
                else:
                    yield Move(i, dst)
            elif self.ep is not None and dst == self.ep:
                yield Move(i, dst, ep=True)

    def jump_moves(self, i, p, deltas):
        side = color_of(p)
        for d in deltas:
            dst = i + d
            if 0 <= dst < 64 and step_ok(i, dst, d):
                t = self.b[dst]
                if t == "." or color_of(t) != side:
                    yield Move(i, dst)

    def slide_moves(self, i, p, deltas):
        side = color_of(p)
        for d in deltas:
            dst = i + d
            while 0 <= dst < 64 and step_ok(dst - d, dst, d):
                t = self.b[dst]
                if t == ".":
                    yield Move(i, dst)
                else:
                    if color_of(t) != side:
                        yield Move(i, dst)
                    break
                dst += d

    def castle_moves(self, i, p):
        if color_of(p) == WHITE and i == 60 and not self.in_check(WHITE):
            if "K" in self.castle and self.b[61] == self.b[62] == ".":
                if not self.attacked(61, BLACK) and not self.attacked(62, BLACK):
                    yield Move(60, 62, castle=True)
            if "Q" in self.castle and self.b[59] == self.b[58] == self.b[57] == ".":
                if not self.attacked(59, BLACK) and not self.attacked(58, BLACK):
                    yield Move(60, 58, castle=True)
        if color_of(p) == BLACK and i == 4 and not self.in_check(BLACK):
            if "k" in self.castle and self.b[5] == self.b[6] == ".":
                if not self.attacked(5, WHITE) and not self.attacked(6, WHITE):
                    yield Move(4, 6, castle=True)
            if "q" in self.castle and self.b[3] == self.b[2] == self.b[1] == ".":
                if not self.attacked(3, WHITE) and not self.attacked(2, WHITE):
                    yield Move(4, 2, castle=True)

    def legal_moves(self):
        moves = []
        side = self.side
        for m in self.pseudo_moves():
            st = self.push(m)
            ok = not self.in_check(side)
            self.pop(st)
            if ok:
                moves.append(m)
        return moves

    def push(self, m):
        piece = self.b[m.src]
        captured = self.b[m.dst]
        state = (m, captured, self.castle, self.ep, self.halfmove, self.fullmove)
        self.b[m.src] = "."
        if m.ep:
            cap_sq = m.dst + (8 if self.side == WHITE else -8)
            captured = self.b[cap_sq]
            self.b[cap_sq] = "."
            state = (m, captured, self.castle, self.ep, self.halfmove, self.fullmove)
        self.b[m.dst] = piece if not m.promo else (m.promo.upper() if self.side == WHITE else m.promo.lower())
        if m.castle:
            if m.dst == 62:
                self.b[61], self.b[63] = self.b[63], "."
            elif m.dst == 58:
                self.b[59], self.b[56] = self.b[56], "."
            elif m.dst == 6:
                self.b[5], self.b[7] = self.b[7], "."
            elif m.dst == 2:
                self.b[3], self.b[0] = self.b[0], "."
        self.update_castle(piece, m.src, m.dst)
        self.ep = None
        if piece.upper() == "P" and abs(m.dst - m.src) == 16:
            self.ep = (m.src + m.dst) // 2
        self.halfmove = 0 if piece.upper() == "P" or captured != "." else self.halfmove + 1
        if self.side == BLACK:
            self.fullmove += 1
        self.side = 1 - self.side
        return state

    def pop(self, state):
        m, captured, self.castle, self.ep, self.halfmove, self.fullmove = state
        self.side = 1 - self.side
        piece = self.b[m.dst]
        if m.promo:
            piece = "P" if self.side == WHITE else "p"
        self.b[m.src] = piece
        self.b[m.dst] = captured
        if m.ep:
            self.b[m.dst] = "."
            self.b[m.dst + (8 if self.side == WHITE else -8)] = captured
        if m.castle:
            if m.dst == 62:
                self.b[63], self.b[61] = self.b[61], "."
            elif m.dst == 58:
                self.b[56], self.b[59] = self.b[59], "."
            elif m.dst == 6:
                self.b[7], self.b[5] = self.b[5], "."
            elif m.dst == 2:
                self.b[0], self.b[3] = self.b[3], "."

    def update_castle(self, piece, src, dst):
        remove = ""
        if piece == "K":
            remove += "KQ"
        elif piece == "k":
            remove += "kq"
        for sq, flag in ((63, "K"), (56, "Q"), (7, "k"), (0, "q")):
            if src == sq or dst == sq:
                remove += flag
        self.castle = "".join(c for c in self.castle if c not in remove)

    def play_uci(self, text):
        src, dst = parse_sq(text[:2]), parse_sq(text[2:4])
        promo = text[4:5].lower()
        if src is None or dst is None:
            return
        for m in self.legal_moves():
            if m.src == src and m.dst == dst and (m.promo == promo or (not m.promo and not promo)):
                self.push(m)
                return


def pst(piece, sq):
    rank = 7 - sq // 8 if piece.isupper() else sq // 8
    file = sq % 8
    center = 3 - min(abs(file - 3), abs(file - 4))
    up = piece.upper()
    if up == "P":
        return rank * 9 + center * 3
    if up in ("N", "B"):
        return center * 10 + (3 - abs(rank - 3)) * 4
    if up == "R":
        return rank * 2
    if up == "Q":
        return center * 3
    if up == "K":
        return -center * 5 if rank < 6 else center * 2
    return 0


def evaluate(board):
    score = 0
    for sq, p in enumerate(board.b):
        if p == ".":
            continue
        val = VALUES[p.upper()] + pst(p, sq)
        score += val if p.isupper() else -val
    return score if board.side == WHITE else -score


def move_score(board, m):
    moving = board.b[m.src]
    target = board.b[m.dst]
    score = 0
    if target != ".":
        score += 10 * VALUES[target.upper()] - VALUES[moving.upper()]
    if m.promo:
        score += VALUES[m.promo.upper()]
    if m.castle:
        score += 30
    return score


class Search:
    def __init__(self, board, end_time):
        self.board = board
        self.end_time = end_time
        self.nodes = 0
        self.stop = False

    def time_up(self):
        return time.monotonic() >= self.end_time

    def negamax(self, depth, alpha, beta):
        if self.time_up():
            self.stop = True
            return evaluate(self.board)
        self.nodes += 1
        moves = self.board.legal_moves()
        if not moves:
            return -MATE + depth if self.board.in_check(self.board.side) else 0
        if depth <= 0:
            return self.quiesce(alpha, beta)
        moves.sort(key=lambda m: move_score(self.board, m), reverse=True)
        best = -INF
        for m in moves:
            st = self.board.push(m)
            score = -self.negamax(depth - 1, -beta, -alpha)
            self.board.pop(st)
            if self.stop:
                return score
            if score > best:
                best = score
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break
        return best

    def quiesce(self, alpha, beta):
        stand = evaluate(self.board)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        caps = [m for m in self.board.legal_moves() if self.board.b[m.dst] != "." or m.ep or m.promo]
        caps.sort(key=lambda m: move_score(self.board, m), reverse=True)
        for m in caps[:24]:
            if self.time_up():
                self.stop = True
                break
            st = self.board.push(m)
            score = -self.quiesce(-beta, -alpha)
            self.board.pop(st)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha


def choose_move(board, ms):
    moves = board.legal_moves()
    if not moves:
        return None
    moves.sort(key=lambda m: move_score(board, m), reverse=True)
    best = moves[0]
    budget = max(1, ms) / 1000.0
    end_time = time.monotonic() + max(0.001, budget * 0.82)
    depth = 1
    while depth <= 4:
        search = Search(board, end_time)
        local_best, local_score = best, -INF
        for m in moves:
            if search.time_up():
                search.stop = True
                break
            st = board.push(m)
            score = -search.negamax(depth - 1, -INF, INF)
            board.pop(st)
            if search.stop:
                break
            if score > local_score:
                local_score, local_best = score, m
        if search.stop:
            break
        best = local_best
        depth += 1
    return best


def set_position(board, parts):
    try:
        if not parts:
            return
        idx = 0
        if parts[0] == "startpos":
            board.set_fen(START_FEN)
            idx = 1
        elif parts[0] == "fen" and len(parts) >= 7:
            board.set_fen(" ".join(parts[1:7]))
            idx = 7
        if idx < len(parts) and parts[idx] == "moves":
            for mv in parts[idx + 1:]:
                board.play_uci(mv)
    except Exception:
        board.set_fen(START_FEN)


def main():
    board = Board()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        if cmd == "uci":
            print("id name SimpleScratch")
            print("id author OpenAI")
            print("uciok", flush=True)
        elif cmd == "isready":
            print("readyok", flush=True)
        elif cmd == "ucinewgame":
            board.set_fen(START_FEN)
        elif cmd == "position":
            set_position(board, parts[1:])
        elif cmd == "go":
            ms = 20
            if "movetime" in parts:
                try:
                    ms = int(parts[parts.index("movetime") + 1])
                except Exception:
                    ms = 20
            move = choose_move(board, ms)
            print("bestmove " + (move.uci() if move else "0000"), flush=True)
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

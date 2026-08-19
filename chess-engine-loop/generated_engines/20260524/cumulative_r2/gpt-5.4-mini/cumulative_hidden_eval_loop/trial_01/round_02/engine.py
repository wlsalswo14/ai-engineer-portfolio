import sys
import time
from dataclasses import dataclass


FILES = "abcdefgh"
WHITE, BLACK = 0, 1
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = range(6)
PIECE_TO_CHAR = "PNBRQK"
CHAR_TO_PIECE = {c: i for i, c in enumerate(PIECE_TO_CHAR)}
MATE = 100000
INF = 10**9

PIECE_VALUES = [100, 320, 330, 500, 900, 0]

PST = {
    PAWN: (
        0, 0, 0, 0, 0, 0, 0, 0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
        5, 5, 10, 25, 25, 10, 5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, -5, -10, 0, 0, -10, -5, 5,
        5, 10, 10, -20, -20, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ),
    KNIGHT: (
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50,
    ),
    BISHOP: (
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -20, -10, -10, -10, -10, -10, -10, -20,
    ),
    ROOK: (
        0, 0, 0, 5, 5, 0, 0, 0,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        5, 10, 10, 10, 10, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ),
    QUEEN: (
        -20, -10, -10, -5, -5, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 5, 5, 5, 0, -10,
        -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5,
        -10, 5, 5, 5, 5, 5, 0, -10,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, -5, -5, -10, -10, -20,
    ),
    KING: (
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20,
        20, 30, 10, 0, 0, 10, 30, 20,
    ),
}

KNIGHT_OFFSETS = (-17, -15, -10, -6, 6, 10, 15, 17)
KING_OFFSETS = (-9, -8, -7, -1, 1, 7, 8, 9)


def sq_to_idx(s):
    return (int(s[1]) - 1) * 8 + (ord(s[0]) - 97)


def idx_to_sq(i):
    return FILES[i & 7] + str((i >> 3) + 1)


@dataclass
class Move:
    from_sq: int
    to_sq: int
    promotion: int = -1
    flag: int = 0

    def uci(self):
        s = idx_to_sq(self.from_sq) + idx_to_sq(self.to_sq)
        if self.promotion >= 0:
            s += "nbrq"[self.promotion - 1]
        return s


class Position:
    def __init__(self):
        self.set_fen("startpos")

    def clone(self):
        p = Position.__new__(Position)
        p.board = self.board[:]
        p.side = self.side
        p.castling = self.castling
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        return p

    def set_fen(self, fen):
        if fen == "startpos":
            fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        parts = fen.split()
        if len(parts) < 4:
            parts = "8/8/8/8/8/8/8/8 w - - 0 1".split()
        board_part, side, castling, ep = parts[:4]
        self.board = [None] * 64
        rows = board_part.split("/")
        if len(rows) == 8:
            for r, row in enumerate(rows[::-1]):
                f = 0
                for ch in row:
                    if ch.isdigit():
                        f += int(ch)
                    elif ch.isalpha() and f < 8:
                        color = WHITE if ch.isupper() else BLACK
                        self.board[r * 8 + f] = (color, CHAR_TO_PIECE[ch.upper()])
                        f += 1
        self.side = WHITE if side == "w" else BLACK
        self.castling = castling if castling != "-" else ""
        self.ep = -1 if ep == "-" else sq_to_idx(ep)
        self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

    def king_sq(self, color):
        for i, p in enumerate(self.board):
            if p == (color, KING):
                return i
        return -1

    def on_board(self, sq):
        return 0 <= sq < 64

    def attacks_square(self, sq, by_color):
        b = self.board
        r, f = divmod(sq, 8)

        pawn_dirs = (-9, -7) if by_color == WHITE else (7, 9)
        for d in pawn_dirs:
            t = sq + d
            if self.on_board(t):
                tr, tf = divmod(t, 8)
                if abs(tf - f) == 1 and b[t] == (by_color, PAWN):
                    return True

        for d in KNIGHT_OFFSETS:
            t = sq + d
            if self.on_board(t):
                tr, tf = divmod(t, 8)
                if max(abs(tr - r), abs(tf - f)) == 2 and b[t] == (by_color, KNIGHT):
                    return True

        for d in (-9, -7, 7, 9):
            t = sq + d
            while self.on_board(t):
                tr, tf = divmod(t, 8)
                if abs(tf - f) != abs(tr - r):
                    break
                piece = b[t]
                if piece:
                    if piece == (by_color, BISHOP) or piece == (by_color, QUEEN):
                        return True
                    break
                if (d == -9 and tf == 0) or (d == -7 and tf == 7) or (d == 7 and tf == 0) or (d == 9 and tf == 7):
                    break
                t += d

        for d in (-8, -1, 1, 8):
            t = sq + d
            while self.on_board(t):
                tr, tf = divmod(t, 8)
                if d in (-1, 1) and tr != r:
                    break
                piece = b[t]
                if piece:
                    if piece == (by_color, ROOK) or piece == (by_color, QUEEN):
                        return True
                    break
                if (d == -1 and tf == 0) or (d == 1 and tf == 7):
                    break
                t += d

        for d in KING_OFFSETS:
            t = sq + d
            if self.on_board(t):
                tr, tf = divmod(t, 8)
                if max(abs(tr - r), abs(tf - f)) == 1 and b[t] == (by_color, KING):
                    return True
        return False

    def in_check(self, color=None):
        if color is None:
            color = self.side
        ks = self.king_sq(color)
        return ks >= 0 and self.attacks_square(ks, BLACK if color == WHITE else WHITE)

    def gen_pseudo(self):
        b = self.board
        color = self.side
        enemy = BLACK if color == WHITE else WHITE
        moves = []

        for sq, piece in enumerate(b):
            if not piece or piece[0] != color:
                continue
            _, pt = piece
            r, f = divmod(sq, 8)

            if pt == PAWN:
                step = 8 if color == WHITE else -8
                start_rank = 1 if color == WHITE else 6
                promo_rank = 6 if color == WHITE else 1
                one = sq + step
                if self.on_board(one) and b[one] is None:
                    if r == promo_rank:
                        for p in (KNIGHT, BISHOP, ROOK, QUEEN):
                            moves.append(Move(sq, one, p))
                    else:
                        moves.append(Move(sq, one))
                        two = sq + 2 * step
                        if r == start_rank and self.on_board(two) and b[two] is None:
                            moves.append(Move(sq, two, flag=1))
                for cap in (step - 1, step + 1):
                    t = sq + cap
                    if not self.on_board(t):
                        continue
                    tr, tf = divmod(t, 8)
                    if abs(tf - f) != 1:
                        continue
                    if b[t] and b[t][0] == enemy:
                        if r == promo_rank:
                            for p in (KNIGHT, BISHOP, ROOK, QUEEN):
                                moves.append(Move(sq, t, p))
                        else:
                            moves.append(Move(sq, t))
                    if t == self.ep:
                        moves.append(Move(sq, t, flag=2))

            elif pt == KNIGHT:
                for d in KNIGHT_OFFSETS:
                    t = sq + d
                    if not self.on_board(t):
                        continue
                    tr, tf = divmod(t, 8)
                    if max(abs(tr - r), abs(tf - f)) != 2:
                        continue
                    if not b[t] or b[t][0] == enemy:
                        moves.append(Move(sq, t))

            elif pt in (BISHOP, ROOK, QUEEN):
                dirs = (-9, -7, 7, 9) if pt == BISHOP else (-8, -1, 1, 8) if pt == ROOK else (-9, -7, 7, 9, -8, -1, 1, 8)
                for d in dirs:
                    t = sq + d
                    while self.on_board(t):
                        tr, tf = divmod(t, 8)
                        if d in (-9, 7) and tf > f:
                            break
                        if d in (-7, 9) and tf < f:
                            break
                        if d == -1 and tr != r:
                            break
                        if d == 1 and tr != r:
                            break
                        if b[t] is None:
                            moves.append(Move(sq, t))
                        else:
                            if b[t][0] == enemy:
                                moves.append(Move(sq, t))
                            break
                        t += d

            else:
                for d in KING_OFFSETS:
                    t = sq + d
                    if not self.on_board(t):
                        continue
                    tr, tf = divmod(t, 8)
                    if max(abs(tr - r), abs(tf - f)) != 1:
                        continue
                    if not b[t] or b[t][0] == enemy:
                        moves.append(Move(sq, t))
                if color == WHITE and sq == 4:
                    if "K" in self.castling and b[5] is None and b[6] is None and not self.in_check(WHITE) and not self.attacks_square(5, enemy) and not self.attacks_square(6, enemy) and b[7] == (WHITE, ROOK):
                        moves.append(Move(4, 6, flag=3))
                    if "Q" in self.castling and b[3] is None and b[2] is None and b[1] is None and not self.in_check(WHITE) and not self.attacks_square(3, enemy) and not self.attacks_square(2, enemy) and b[0] == (WHITE, ROOK):
                        moves.append(Move(4, 2, flag=4))
                if color == BLACK and sq == 60:
                    if "k" in self.castling and b[61] is None and b[62] is None and not self.in_check(BLACK) and not self.attacks_square(61, enemy) and not self.attacks_square(62, enemy) and b[63] == (BLACK, ROOK):
                        moves.append(Move(60, 62, flag=3))
                    if "q" in self.castling and b[59] is None and b[58] is None and b[57] is None and not self.in_check(BLACK) and not self.attacks_square(59, enemy) and not self.attacks_square(58, enemy) and b[56] == (BLACK, ROOK):
                        moves.append(Move(60, 58, flag=4))
        return moves

    def make_move(self, mv):
        b = self.board
        piece = b[mv.from_sq]
        if piece is None:
            return None
        color, pt = piece
        captured = b[mv.to_sq]
        undo = (mv, captured, self.castling, self.ep, self.halfmove, self.fullmove)

        self.ep = -1
        self.halfmove += 1
        if pt == PAWN or captured:
            self.halfmove = 0

        b[mv.from_sq] = None

        if mv.flag == 2:
            cap_sq = mv.to_sq - (8 if color == WHITE else -8)
            captured = b[cap_sq]
            b[cap_sq] = None
            self.halfmove = 0
        elif mv.flag == 3:
            if color == WHITE:
                b[7] = None
                b[5] = (WHITE, ROOK)
            else:
                b[63] = None
                b[61] = (BLACK, ROOK)
        elif mv.flag == 4:
            if color == WHITE:
                b[0] = None
                b[3] = (WHITE, ROOK)
            else:
                b[56] = None
                b[59] = (BLACK, ROOK)

        if pt == PAWN and abs(mv.to_sq - mv.from_sq) == 16:
            self.ep = (mv.from_sq + mv.to_sq) // 2

        if pt == KING:
            if color == WHITE:
                self.castling = self.castling.replace("K", "").replace("Q", "")
            else:
                self.castling = self.castling.replace("k", "").replace("q", "")
        elif pt == ROOK:
            if mv.from_sq == 0:
                self.castling = self.castling.replace("Q", "")
            elif mv.from_sq == 7:
                self.castling = self.castling.replace("K", "")
            elif mv.from_sq == 56:
                self.castling = self.castling.replace("q", "")
            elif mv.from_sq == 63:
                self.castling = self.castling.replace("k", "")

        if captured and captured[1] == ROOK:
            if mv.to_sq == 0:
                self.castling = self.castling.replace("Q", "")
            elif mv.to_sq == 7:
                self.castling = self.castling.replace("K", "")
            elif mv.to_sq == 56:
                self.castling = self.castling.replace("q", "")
            elif mv.to_sq == 63:
                self.castling = self.castling.replace("k", "")

        b[mv.to_sq] = (color, mv.promotion if mv.promotion >= 0 else pt)
        self.side = BLACK if self.side == WHITE else WHITE
        if self.side == WHITE:
            self.fullmove += 1

        if self.in_check(BLACK if self.side == WHITE else WHITE):
            self.unmake_move(undo)
            return None
        return undo

    def unmake_move(self, undo):
        mv, captured, castling, ep, halfmove, fullmove = undo
        self.side = BLACK if self.side == WHITE else WHITE
        self.castling, self.ep, self.halfmove, self.fullmove = castling, ep, halfmove, fullmove
        b = self.board
        color = self.side
        pt = b[mv.to_sq][1]
        b[mv.to_sq] = captured
        if mv.flag == 2:
            cap_sq = mv.to_sq - (8 if color == WHITE else -8)
            b[cap_sq] = (BLACK if color == WHITE else WHITE, PAWN)
        elif mv.flag == 3:
            if color == WHITE:
                b[7] = (WHITE, ROOK)
                b[5] = None
            else:
                b[63] = (BLACK, ROOK)
                b[61] = None
        elif mv.flag == 4:
            if color == WHITE:
                b[0] = (WHITE, ROOK)
                b[3] = None
            else:
                b[56] = (BLACK, ROOK)
                b[59] = None
        b[mv.from_sq] = (color, KING if pt == KING and mv.flag in (3, 4) else (mv.promotion if mv.promotion >= 0 else pt))

    def legal_moves(self):
        out = []
        for mv in self.gen_pseudo():
            undo = self.make_move(mv)
            if undo is not None:
                out.append(mv)
                self.unmake_move(undo)
        return out

    def evaluate(self):
        score = 0
        for sq, p in enumerate(self.board):
            if not p:
                continue
            color, pt = p
            val = PIECE_VALUES[pt] + PST[pt][sq if color == WHITE else 63 - sq]
            score += val if color == WHITE else -val
        if self.in_check(WHITE):
            score -= 8
        if self.in_check(BLACK):
            score += 8
        return score if self.side == WHITE else -score


def order_moves(pos, moves):
    scored = []
    for mv in moves:
        score = 0
        target = pos.board[mv.to_sq]
        if target:
            score += 10 * PIECE_VALUES[target[1]] - PIECE_VALUES[pos.board[mv.from_sq][1]]
        if mv.promotion >= 0:
            score += 800 + PIECE_VALUES[mv.promotion]
        if mv.flag in (2, 3, 4):
            score += 50
        scored.append((score, mv))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [mv for _, mv in scored]


def search(pos, depth, alpha, beta, deadline):
    if depth <= 0:
        return pos.evaluate(), None
    moves = order_moves(pos, pos.legal_moves())
    if not moves:
        return ((-MATE + depth) if pos.in_check() else 0), None
    best = None
    for mv in moves:
        if time.time() >= deadline:
            break
        undo = pos.make_move(mv)
        if undo is None:
            continue
        score, _ = search(pos, depth - 1, -beta, -alpha, deadline)
        score = -score
        pos.unmake_move(undo)
        if score > alpha:
            alpha = score
            best = mv
            if alpha >= beta:
                break
    return alpha, best


class Engine:
    def __init__(self):
        self.pos = Position()

    def set_position(self, tokens):
        if not tokens:
            return
        if tokens[0] == "startpos":
            self.pos.set_fen("startpos")
            tokens = tokens[1:]
        elif tokens[0] == "fen":
            fen = " ".join(tokens[1:7])
            self.pos.set_fen(fen if fen else "8/8/8/8/8/8/8/8 w - - 0 1")
            tokens = tokens[7:]
        else:
            return
        if tokens and tokens[0] == "moves":
            for m in tokens[1:]:
                self.play_uci(m)

    def play_uci(self, m):
        for mv in self.pos.legal_moves():
            if mv.uci() == m:
                self.pos.make_move(mv)
                return

    def bestmove(self, movetime):
        legal = self.pos.legal_moves()
        if not legal:
            return "0000"
        best = legal[0]
        deadline = time.time() + max(1, movetime) / 1000.0 - 0.003
        depth = 1
        while depth <= 5 and time.time() < deadline:
            _, mv = search(self.pos, depth, -INF, INF, deadline)
            if mv is not None:
                best = mv
            depth += 1
        return best.uci()


def main():
    eng = Engine()
    out = sys.stdout
    for raw in sys.stdin:
        cmd = raw.strip()
        if not cmd:
            continue
        parts = cmd.split()
        if parts[0] == "uci":
            print("id name MinimalPythonEngine")
            print("id author openai")
            print("uciok")
            out.flush()
        elif parts[0] == "isready":
            print("readyok")
            out.flush()
        elif parts[0] == "ucinewgame":
            eng = Engine()
        elif parts[0] == "position":
            eng.set_position(parts[1:])
        elif parts[0] == "go":
            movetime = 20
            if "movetime" in parts:
                try:
                    movetime = int(parts[parts.index("movetime") + 1])
                except Exception:
                    movetime = 20
            print("bestmove", eng.bestmove(movetime))
            out.flush()
        elif parts[0] == "quit":
            break


if __name__ == "__main__":
    main()

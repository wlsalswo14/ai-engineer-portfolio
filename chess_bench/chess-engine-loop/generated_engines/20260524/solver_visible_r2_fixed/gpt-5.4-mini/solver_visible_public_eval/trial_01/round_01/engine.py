import sys
import time

WHITE, BLACK = 0, 1

PIECE_VALUES = {
    "P": 100,
    "N": 320,
    "B": 330,
    "R": 500,
    "Q": 900,
    "K": 0,
}

KNIGHT_DELTAS = (-17, -15, -10, -6, 6, 10, 15, 17)
BISHOP_DELTAS = (-9, -7, 7, 9)
ROOK_DELTAS = (-8, -1, 1, 8)
KING_DELTAS = (-9, -8, -7, -1, 1, 7, 8, 9)

FILES = "abcdefgh"


def sq_to_uci(sq):
    return FILES[sq % 8] + str(1 + sq // 8)


def uci_to_sq(s):
    return (int(s[1]) - 1) * 8 + (ord(s[0]) - 97)


def on_board(sq):
    return 0 <= sq < 64


def same_file(a, b):
    return a % 8 == b % 8


def same_rank(a, b):
    return a // 8 == b // 8


class Board:
    def __init__(self):
        self.reset()

    def reset(self):
        self.squares = [None] * 64
        self.side = WHITE
        self.castling = set("KQkq")
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = {WHITE: 4, BLACK: 60}
        self.history = []
        self.set_startpos()

    def set_startpos(self):
        self.squares = [None] * 64
        back = "RNBQKBNR"
        for i, p in enumerate(back):
            self.squares[i] = p
            self.squares[8 + i] = "P"
            self.squares[48 + i] = p.lower()
            self.squares[56 + i] = "p"
        self.side = WHITE
        self.castling = set("KQkq")
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = {WHITE: 4, BLACK: 60}
        self.history = []

    def piece_color(self, p):
        return WHITE if p.isupper() else BLACK

    def is_enemy(self, p, side):
        return p is not None and self.piece_color(p) != side

    def parse_fen(self, fen):
        parts = fen.split()
        if len(parts) != 6:
            self.set_startpos()
            return
        rows = parts[0].split("/")
        if len(rows) != 8:
            self.set_startpos()
            return
        self.squares = [None] * 64
        self.king_sq = {WHITE: None, BLACK: None}
        for r, row in enumerate(reversed(rows)):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                else:
                    self.squares[r * 8 + f] = ch
                    if ch == "K":
                        self.king_sq[WHITE] = r * 8 + f
                    elif ch == "k":
                        self.king_sq[BLACK] = r * 8 + f
                    f += 1
        self.side = WHITE if parts[1] == "w" else BLACK
        self.castling = set(parts[2]) if parts[2] != "-" else set()
        self.ep = None if parts[3] == "-" else uci_to_sq(parts[3])
        self.halfmove = int(parts[4]) if parts[4].isdigit() else 0
        self.fullmove = int(parts[5]) if parts[5].isdigit() else 1
        if self.king_sq[WHITE] is None:
            self.king_sq[WHITE] = self.find_king(WHITE)
        if self.king_sq[BLACK] is None:
            self.king_sq[BLACK] = self.find_king(BLACK)
        self.history = []

    def find_king(self, side):
        target = "K" if side == WHITE else "k"
        for i, p in enumerate(self.squares):
            if p == target:
                return i
        return 4 if side == WHITE else 60

    def attacked_by(self, sq, by_side):
        # Pawns
        if by_side == WHITE:
            for d in (-7, -9):
                s = sq + d
                if on_board(s) and self.squares[s] == "P":
                    if abs((s % 8) - (sq % 8)) == 1:
                        return True
        else:
            for d in (7, 9):
                s = sq + d
                if on_board(s) and self.squares[s] == "p":
                    if abs((s % 8) - (sq % 8)) == 1:
                        return True
        # Knights
        knight = "N" if by_side == WHITE else "n"
        for d in KNIGHT_DELTAS:
            s = sq + d
            if on_board(s) and self.squares[s] == knight:
                if abs((s % 8) - (sq % 8)) in (1, 2):
                    return True
        # Bishops/Queens
        bishop = "B" if by_side == WHITE else "b"
        queen = "Q" if by_side == WHITE else "q"
        for d in BISHOP_DELTAS:
            s = sq + d
            while on_board(s) and abs((s % 8) - ((s - d) % 8)) == 1:
                p = self.squares[s]
                if p:
                    if p in (bishop, queen):
                        return True
                    break
                s += d
        # Rooks/Queens
        rook = "R" if by_side == WHITE else "r"
        for d in ROOK_DELTAS:
            s = sq + d
            while on_board(s) and (d in (-1, 1) and same_rank(s, s - d) or d in (-8, 8)):
                p = self.squares[s]
                if p:
                    if p in (rook, queen):
                        return True
                    break
                s += d
        # King
        king = "K" if by_side == WHITE else "k"
        for d in KING_DELTAS:
            s = sq + d
            if on_board(s) and self.squares[s] == king:
                if max(abs((s % 8) - (sq % 8)), abs((s // 8) - (sq // 8))) == 1:
                    return True
        return False

    def in_check(self, side):
        return self.king_sq[side] is not None and self.attacked_by(self.king_sq[side], 1 - side)

    def push(self, move):
        frm, to, promo, flags = move
        piece = self.squares[frm]
        captured = self.squares[to]
        state = (move, captured, self.ep, self.castling.copy(), self.halfmove, self.fullmove, self.king_sq.copy())
        self.history.append(state)
        self.squares[frm] = None
        self.ep = None
        if piece in ("P", "p") or captured:
            self.halfmove = 0
        else:
            self.halfmove += 1
        if piece == "K":
            self.king_sq[WHITE] = to
            self.castling.discard("K")
            self.castling.discard("Q")
            if flags == "castle":
                if to == 6:
                    self.squares[5] = self.squares[7]
                    self.squares[7] = None
                elif to == 2:
                    self.squares[3] = self.squares[0]
                    self.squares[0] = None
        elif piece == "k":
            self.king_sq[BLACK] = to
            self.castling.discard("k")
            self.castling.discard("q")
            if flags == "castle":
                if to == 62:
                    self.squares[61] = self.squares[63]
                    self.squares[63] = None
                elif to == 58:
                    self.squares[59] = self.squares[56]
                    self.squares[56] = None
        if frm == 0:
            self.castling.discard("Q")
        elif frm == 7:
            self.castling.discard("K")
        elif frm == 56:
            self.castling.discard("q")
        elif frm == 63:
            self.castling.discard("k")
        if to == 0:
            self.castling.discard("Q")
        elif to == 7:
            self.castling.discard("K")
        elif to == 56:
            self.castling.discard("q")
        elif to == 63:
            self.castling.discard("k")
        if flags == "ep":
            cap_sq = to - 8 if piece == "P" else to + 8
            captured = self.squares[cap_sq]
            self.squares[cap_sq] = None
        if piece == "P" and to - frm == 16:
            self.ep = frm + 8
        elif piece == "p" and frm - to == 16:
            self.ep = frm - 8
        if promo:
            piece = promo if self.side == WHITE else promo.lower()
        self.squares[to] = piece
        if self.side == BLACK:
            self.fullmove += 1
        self.side = 1 - self.side

    def pop(self):
        move, captured, ep, castling, halfmove, fullmove, kings = self.history.pop()
        frm, to, promo, flags = move
        self.side = 1 - self.side
        self.squares[frm] = self.squares[to]
        if promo:
            self.squares[frm] = "P" if self.side == WHITE else "p"
        self.squares[to] = captured
        self.ep = ep
        self.castling = castling
        self.halfmove = halfmove
        self.fullmove = fullmove
        self.king_sq = kings
        if flags == "ep":
            cap_sq = to - 8 if self.side == WHITE else to + 8
            self.squares[cap_sq] = "p" if self.side == WHITE else "P"
        if flags == "castle":
            if to == 6:
                self.squares[7] = self.squares[5]
                self.squares[5] = None
            elif to == 2:
                self.squares[0] = self.squares[3]
                self.squares[3] = None
            elif to == 62:
                self.squares[63] = self.squares[61]
                self.squares[61] = None
            elif to == 58:
                self.squares[56] = self.squares[59]
                self.squares[59] = None

    def gen_pseudo(self):
        side = self.side
        for sq, p in enumerate(self.squares):
            if not p or self.piece_color(p) != side:
                continue
            up = p.upper()
            if up == "P":
                direction = 8 if side == WHITE else -8
                start_rank = 1 if side == WHITE else 6
                promo_rank = 6 if side == WHITE else 1
                one = sq + direction
                if on_board(one) and self.squares[one] is None:
                    if sq // 8 == promo_rank:
                        for promo in "QRBN":
                            yield (sq, one, promo, None)
                    else:
                        yield (sq, one, None, None)
                    two = sq + 2 * direction
                    if sq // 8 == start_rank and self.squares[two] is None:
                        yield (sq, two, None, None)
                for cap_dir in (direction - 1, direction + 1):
                    to = sq + cap_dir
                    if not on_board(to):
                        continue
                    if abs((to % 8) - (sq % 8)) != 1:
                        continue
                    target = self.squares[to]
                    if target and self.piece_color(target) != side:
                        if sq // 8 == promo_rank:
                            for promo in "QRBN":
                                yield (sq, to, promo, None)
                        else:
                            yield (sq, to, None, None)
                    if self.ep == to:
                        yield (sq, to, None, "ep")
            elif up == "N":
                for d in KNIGHT_DELTAS:
                    to = sq + d
                    if on_board(to) and abs((to % 8) - (sq % 8)) in (1, 2):
                        target = self.squares[to]
                        if not target or self.piece_color(target) != side:
                            yield (sq, to, None, None)
            elif up in ("B", "R", "Q"):
                dirs = []
                if up in ("B", "Q"):
                    dirs += BISHOP_DELTAS
                if up in ("R", "Q"):
                    dirs += ROOK_DELTAS
                for d in dirs:
                    to = sq + d
                    while on_board(to):
                        if d in (-1, 1) and not same_rank(to, to - d):
                            break
                        if abs((to % 8) - ((to - d) % 8)) > 1 and d in (-9, -7, 7, 9):
                            break
                        target = self.squares[to]
                        if not target:
                            yield (sq, to, None, None)
                        else:
                            if self.piece_color(target) != side:
                                yield (sq, to, None, None)
                            break
                        to += d
            elif up == "K":
                for d in KING_DELTAS:
                    to = sq + d
                    if on_board(to) and max(abs((to % 8) - (sq % 8)), abs((to // 8) - (sq // 8))) == 1:
                        target = self.squares[to]
                        if not target or self.piece_color(target) != side:
                            yield (sq, to, None, None)
                if side == WHITE and sq == 4 and not self.in_check(WHITE):
                    if "K" in self.castling and self.squares[5] is None and self.squares[6] is None:
                        if not self.attacked_by(5, BLACK) and not self.attacked_by(6, BLACK):
                            yield (4, 6, None, "castle")
                    if "Q" in self.castling and self.squares[1] is None and self.squares[2] is None and self.squares[3] is None:
                        if not self.attacked_by(3, BLACK) and not self.attacked_by(2, BLACK):
                            yield (4, 2, None, "castle")
                elif side == BLACK and sq == 60 and not self.in_check(BLACK):
                    if "k" in self.castling and self.squares[61] is None and self.squares[62] is None:
                        if not self.attacked_by(61, WHITE) and not self.attacked_by(62, WHITE):
                            yield (60, 62, None, "castle")
                    if "q" in self.castling and self.squares[57] is None and self.squares[58] is None and self.squares[59] is None:
                        if not self.attacked_by(59, WHITE) and not self.attacked_by(58, WHITE):
                            yield (60, 58, None, "castle")

    def legal_moves(self):
        moves = []
        for m in self.gen_pseudo():
            self.push(m)
            if not self.in_check(1 - self.side):
                moves.append(m)
            self.pop()
        return moves

    def move_to_uci(self, move):
        frm, to, promo, flags = move
        s = sq_to_uci(frm) + sq_to_uci(to)
        if promo:
            s += promo.lower()
        return s


class Engine:
    def __init__(self):
        self.board = Board()
        self.deadline = 0.0

    def evaluate(self):
        score = 0
        for sq, p in enumerate(self.board.squares):
            if not p:
                continue
            val = PIECE_VALUES[p.upper()]
            if p.isupper():
                score += val
            else:
                score -= val
        if self.board.in_check(WHITE):
            score -= 5
        if self.board.in_check(BLACK):
            score += 5
        return score if self.board.side == WHITE else -score

    def ordered_moves(self, moves):
        def key(m):
            frm, to, promo, flags = m
            target = self.board.squares[to]
            score = 0
            if flags == "castle":
                score += 50
            if flags == "ep":
                score += 105
            if target:
                score += 10 * PIECE_VALUES[target.upper()] - PIECE_VALUES[self.board.squares[frm].upper()]
            if promo:
                score += PIECE_VALUES[promo]
            return -score

        return sorted(moves, key=key)

    def search(self, depth, alpha, beta):
        if time.time() >= self.deadline:
            raise TimeoutError
        moves = self.board.legal_moves()
        if not moves:
            return -100000 + (5 - depth) if self.board.in_check(self.board.side) else 0
        if depth == 0:
            return self.evaluate()
        best = -10**9
        for m in self.ordered_moves(moves):
            self.board.push(m)
            score = -self.search(depth - 1, -beta, -alpha)
            self.board.pop()
            if score > best:
                best = score
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break
            if time.time() >= self.deadline:
                raise TimeoutError
        return best

    def bestmove(self, movetime_ms):
        legal = self.board.legal_moves()
        if not legal:
            return "0000"
        return self.board.move_to_uci(legal[0])

    def apply_position(self, tokens):
        if not tokens:
            return
        i = 0
        if tokens[i] == "startpos":
            self.board.set_startpos()
            i += 1
        elif tokens[i] == "fen":
            fen = " ".join(tokens[i + 1:i + 7])
            self.board.parse_fen(fen)
            i += 7
        else:
            return
        if i < len(tokens) and tokens[i] == "moves":
            i += 1
            while i < len(tokens):
                self.apply_uci_move(tokens[i])
                i += 1

    def apply_uci_move(self, mv):
        legal = self.board.legal_moves()
        for m in legal:
            if self.board.move_to_uci(m) == mv:
                self.board.push(m)
                return


def main():
    eng = Engine()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "uci":
            print("id name MinimalPythonEngine")
            print("id author openai")
            print("uciok")
            sys.stdout.flush()
        elif line == "isready":
            print("readyok")
            sys.stdout.flush()
        elif line == "ucinewgame":
            eng.board.set_startpos()
        elif line.startswith("position "):
            eng.apply_position(line.split()[1:])
        elif line.startswith("go "):
            parts = line.split()
            mt = 20
            for i, t in enumerate(parts):
                if t == "movetime" and i + 1 < len(parts):
                    try:
                        mt = int(parts[i + 1])
                    except ValueError:
                        mt = 20
            print("bestmove", eng.bestmove(mt))
            sys.stdout.flush()
        elif line == "quit":
            break


if __name__ == "__main__":
    main()

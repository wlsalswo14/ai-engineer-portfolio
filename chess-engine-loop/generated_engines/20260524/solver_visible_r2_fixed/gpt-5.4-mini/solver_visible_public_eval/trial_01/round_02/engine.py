#!/usr/bin/env python3
import sys
import time

WHITE, BLACK = 0, 1

FILES = "abcdefgh"
PROMOS = "qrbn"

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

PAWN_PST = [
      0,   0,   0,   0,   0,   0,   0,   0,
     10,  10,  10, -10, -10,  10,  10,  10,
      6,   6,   8,  12,  12,   8,   6,   6,
      4,   4,   6,  16,  16,   6,   4,   4,
      3,   3,   4,  12,  12,   4,   3,   3,
      2,   2,   2,   8,   8,   2,   2,   2,
      2,   2,  -2, -10, -10,  -2,   2,   2,
      0,   0,   0,   0,   0,   0,   0,   0,
]

KNIGHT_PST = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -30,   5,  10,  15,  15,  10,   5, -30,
    -30,   0,  15,  20,  20,  15,   0, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,   0,  10,  15,  15,  10,   0, -30,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]

BISHOP_PST = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -10,   5,   5,  10,  10,   5,   5, -10,
    -10,   0,  10,  10,  10,  10,   0, -10,
    -10,  10,  10,  10,  10,  10,  10, -10,
    -10,   5,   0,   0,   0,   0,   5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]

ROOK_PST = [
      0,   0,   0,   5,   5,   0,   0,   0,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
      5,  10,  10,  10,  10,  10,  10,   5,
      0,   0,   0,   0,   0,   0,   0,   0,
]

QUEEN_PST = [
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   5,   0, -10,
    -10,   0,   5,   5,   5,   5,   5, -10,
     -5,   0,   5,   5,   5,   5,   0,  -5,
      0,   0,   5,   5,   5,   5,   0,  -5,
    -10,   5,   5,   5,   5,   5,   0, -10,
    -10,   0,   5,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20,
]

KING_MID_PST = [
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
     20,  20,   0,   0,   0,   0,  20,  20,
     20,  30,  10,   0,   0,  10,  30,  20,
]


def sq_to_uci(sq):
    return FILES[sq & 7] + str((sq >> 3) + 1)


def uci_to_sq(s):
    return ((ord(s[1]) - 49) << 3) + (ord(s[0]) - 97)


def mirror_sq(sq):
    return sq ^ 56


def on_board(sq):
    return 0 <= sq < 64


def file_of(sq):
    return sq & 7


def rank_of(sq):
    return sq >> 3


def piece_color(p):
    return WHITE if p.isupper() else BLACK


def is_enemy(p, side):
    return p is not None and piece_color(p) != side


class Board:
    def __init__(self):
        self.squares = [None] * 64
        self.side = WHITE
        self.castling = set()
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
            self.squares[48 + i] = "p"
            self.squares[56 + i] = p.lower()
        self.side = WHITE
        self.castling = set("KQkq")
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = {WHITE: 4, BLACK: 60}
        self.history = []

    def parse_fen(self, fen):
        try:
            parts = fen.split()
            if len(parts) != 6:
                raise ValueError
            rows = parts[0].split("/")
            if len(rows) != 8:
                raise ValueError
            squares = [None] * 64
            king_sq = {WHITE: None, BLACK: None}
            for fen_rank, row in enumerate(rows):
                sq = (7 - fen_rank) * 8
                for ch in row:
                    if ch.isdigit():
                        sq += int(ch)
                    else:
                        if sq >= 64:
                            raise ValueError
                        squares[sq] = ch
                        if ch == "K":
                            king_sq[WHITE] = sq
                        elif ch == "k":
                            king_sq[BLACK] = sq
                        sq += 1
                if sq != (7 - fen_rank) * 8 + 8:
                    raise ValueError
            self.squares = squares
            self.side = WHITE if parts[1] == "w" else BLACK
            self.castling = set() if parts[2] == "-" else set(parts[2])
            self.ep = None if parts[3] == "-" else uci_to_sq(parts[3])
            self.halfmove = int(parts[4])
            self.fullmove = max(1, int(parts[5]))
            self.king_sq = king_sq
            if self.king_sq[WHITE] is None:
                self.king_sq[WHITE] = self.find_king(WHITE)
            if self.king_sq[BLACK] is None:
                self.king_sq[BLACK] = self.find_king(BLACK)
            self.history = []
        except Exception:
            self.set_startpos()

    def find_king(self, side):
        target = "K" if side == WHITE else "k"
        for i, p in enumerate(self.squares):
            if p == target:
                return i
        return 4 if side == WHITE else 60

    def attacked_by(self, sq, by_side):
        if by_side == WHITE:
            for d in (-7, -9):
                s = sq + d
                if on_board(s) and self.squares[s] == "P" and abs(file_of(s) - file_of(sq)) == 1:
                    return True
        else:
            for d in (7, 9):
                s = sq + d
                if on_board(s) and self.squares[s] == "p" and abs(file_of(s) - file_of(sq)) == 1:
                    return True

        knight = "N" if by_side == WHITE else "n"
        for d in KNIGHT_DELTAS:
            s = sq + d
            if on_board(s) and self.squares[s] == knight and abs(file_of(s) - file_of(sq)) in (1, 2):
                return True

        bishop = "B" if by_side == WHITE else "b"
        rook = "R" if by_side == WHITE else "r"
        queen = "Q" if by_side == WHITE else "q"

        for d in BISHOP_DELTAS:
            s = sq + d
            while on_board(s) and abs(file_of(s) - file_of(s - d)) == 1:
                p = self.squares[s]
                if p is not None:
                    if p == bishop or p == queen:
                        return True
                    break
                s += d

        for d in ROOK_DELTAS:
            s = sq + d
            while on_board(s):
                if d == -1 and file_of(s) == 7:
                    break
                if d == 1 and file_of(s) == 0:
                    break
                p = self.squares[s]
                if p is not None:
                    if p == rook or p == queen:
                        return True
                    break
                s += d

        king = "K" if by_side == WHITE else "k"
        for d in KING_DELTAS:
            s = sq + d
            if on_board(s) and self.squares[s] == king and max(abs(file_of(s) - file_of(sq)), abs(rank_of(s) - rank_of(sq))) == 1:
                return True
        return False

    def in_check(self, side):
        ks = self.king_sq[side]
        return ks is not None and self.attacked_by(ks, 1 - side)

    def push(self, move):
        frm, to, promo, flag = move
        piece = self.squares[frm]
        captured = self.squares[to]
        prev = (move, captured, self.ep, self.castling.copy(), self.halfmove, self.fullmove, self.king_sq.copy())
        self.history.append(prev)

        self.ep = None
        self.squares[frm] = None

        if piece in ("P", "p") or captured is not None or flag == "ep":
            self.halfmove = 0
        else:
            self.halfmove += 1

        if flag == "ep":
            cap_sq = to - 8 if piece == "P" else to + 8
            self.squares[cap_sq] = None

        if piece == "K":
            self.king_sq[WHITE] = to
            self.castling.discard("K")
            self.castling.discard("Q")
            if flag == "castle":
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
            if flag == "castle":
                if to == 62:
                    self.squares[61] = self.squares[63]
                    self.squares[63] = None
                elif to == 58:
                    self.squares[59] = self.squares[56]
                    self.squares[56] = None

        if frm == 0 or to == 0:
            self.castling.discard("Q")
        if frm == 7 or to == 7:
            self.castling.discard("K")
        if frm == 56 or to == 56:
            self.castling.discard("q")
        if frm == 63 or to == 63:
            self.castling.discard("k")

        if piece == "P" and to - frm == 16:
            self.ep = frm + 8
        elif piece == "p" and frm - to == 16:
            self.ep = frm - 8

        placed = piece
        if promo:
            placed = promo.upper() if piece.isupper() else promo.lower()
        self.squares[to] = placed

        if self.side == BLACK:
            self.fullmove += 1
        self.side = 1 - self.side

    def pop(self):
        move, captured, ep, castling, halfmove, fullmove, king_sq = self.history.pop()
        frm, to, promo, flag = move
        self.side = 1 - self.side
        moved_piece = self.squares[to]
        if promo:
            self.squares[frm] = "P" if self.side == WHITE else "p"
        else:
            self.squares[frm] = moved_piece
        self.squares[to] = captured
        self.ep = ep
        self.castling = castling
        self.halfmove = halfmove
        self.fullmove = fullmove
        self.king_sq = king_sq

        if flag == "ep":
            cap_sq = to - 8 if self.side == WHITE else to + 8
            self.squares[cap_sq] = "p" if self.side == WHITE else "P"

        if flag == "castle":
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
            if p is None or piece_color(p) != side:
                continue
            up = p.upper()
            if up == "P":
                step = 8 if side == WHITE else -8
                start_rank = 1 if side == WHITE else 6
                promo_rank = 6 if side == WHITE else 1
                one = sq + step
                if on_board(one) and self.squares[one] is None:
                    if rank_of(sq) == promo_rank:
                        for pr in PROMOS:
                            yield (sq, one, pr, None)
                    else:
                        yield (sq, one, None, None)
                        two = sq + 2 * step
                        if rank_of(sq) == start_rank and on_board(two) and self.squares[two] is None:
                            yield (sq, two, None, None)
                for cap in (step - 1, step + 1):
                    to = sq + cap
                    if not on_board(to):
                        continue
                    if abs(file_of(to) - file_of(sq)) != 1:
                        continue
                    target = self.squares[to]
                    if target is not None and piece_color(target) != side:
                        if rank_of(sq) == promo_rank:
                            for pr in PROMOS:
                                yield (sq, to, pr, None)
                        else:
                            yield (sq, to, None, None)
                    if self.ep == to:
                        yield (sq, to, None, "ep")
            elif up == "N":
                for d in KNIGHT_DELTAS:
                    to = sq + d
                    if on_board(to) and abs(file_of(to) - file_of(sq)) in (1, 2):
                        target = self.squares[to]
                        if target is None or piece_color(target) != side:
                            yield (sq, to, None, None)
            elif up in ("B", "R", "Q"):
                dirs = []
                if up in ("B", "Q"):
                    dirs.extend(BISHOP_DELTAS)
                if up in ("R", "Q"):
                    dirs.extend(ROOK_DELTAS)
                for d in dirs:
                    to = sq + d
                    while on_board(to):
                        if d == -1 and file_of(to) == 7:
                            break
                        if d == 1 and file_of(to) == 0:
                            break
                        if d in (-9, 7) and file_of(to) == 7:
                            break
                        if d in (-7, 9) and file_of(to) == 0:
                            break
                        target = self.squares[to]
                        if target is None:
                            yield (sq, to, None, None)
                        else:
                            if piece_color(target) != side:
                                yield (sq, to, None, None)
                            break
                        to += d
            else:
                for d in KING_DELTAS:
                    to = sq + d
                    if on_board(to) and max(abs(file_of(to) - file_of(sq)), abs(rank_of(to) - rank_of(sq))) == 1:
                        target = self.squares[to]
                        if target is None or piece_color(target) != side:
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
        frm, to, promo, _ = move
        s = sq_to_uci(frm) + sq_to_uci(to)
        if promo:
            s += promo
        return s

    def push_uci(self, mv):
        for m in self.legal_moves():
            if self.move_to_uci(m) == mv:
                self.push(m)
                return True
        return False


class Engine:
    MATE = 100000

    def __init__(self):
        self.board = Board()
        self.deadline = 0.0
        self.nodes = 0
        self.killer = [[None, None] for _ in range(64)]
        self.history = [[[0 for _ in range(64)] for _ in range(64)] for _ in range(2)]
        self.pv = {}

    def pst_score(self, p, sq):
        idx = sq if p.isupper() else mirror_sq(sq)
        t = p.upper()
        if t == "P":
            return PAWN_PST[idx]
        if t == "N":
            return KNIGHT_PST[idx]
        if t == "B":
            return BISHOP_PST[idx]
        if t == "R":
            return ROOK_PST[idx]
        if t == "Q":
            return QUEEN_PST[idx]
        return KING_MID_PST[idx]

    def evaluate(self):
        score = 0
        white_material = 0
        black_material = 0
        for sq, p in enumerate(self.board.squares):
            if p is None:
                continue
            val = PIECE_VALUES[p.upper()] + self.pst_score(p, sq)
            if p.isupper():
                score += val
                white_material += PIECE_VALUES[p.upper()]
            else:
                score -= val
                black_material += PIECE_VALUES[p.upper()]

        score += self.pawn_structure()
        score += self.king_safety()
        score += self.trivial_endgame_bonus(white_material, black_material)
        return score if self.board.side == WHITE else -score

    def pawn_structure(self):
        score = 0
        white_files = [0] * 8
        black_files = [0] * 8
        for sq, p in enumerate(self.board.squares):
            if p == "P":
                white_files[file_of(sq)] += 1
            elif p == "p":
                black_files[file_of(sq)] += 1
        for f in range(8):
            if white_files[f] > 1:
                score -= 10 * (white_files[f] - 1)
            if black_files[f] > 1:
                score += 10 * (black_files[f] - 1)

        for sq, p in enumerate(self.board.squares):
            if p == "P":
                f = file_of(sq)
                if (f == 0 or white_files[f - 1] == 0) and (f == 7 or white_files[f + 1] == 0):
                    score -= 8
            elif p == "p":
                f = file_of(sq)
                if (f == 0 or black_files[f - 1] == 0) and (f == 7 or black_files[f + 1] == 0):
                    score += 8
        return score

    def king_safety(self):
        score = 0
        wk = self.board.king_sq[WHITE]
        bk = self.board.king_sq[BLACK]
        if wk is not None:
            score -= 8 * sum(1 for d in KING_DELTAS if on_board(wk + d) and self.board.squares[wk + d] == "p")
        if bk is not None:
            score += 8 * sum(1 for d in KING_DELTAS if on_board(bk + d) and self.board.squares[bk + d] == "P")
        if self.board.in_check(WHITE):
            score -= 20
        if self.board.in_check(BLACK):
            score += 20
        return score

    def trivial_endgame_bonus(self, wm, bm):
        total = wm + bm
        if total <= 1400:
            wk = self.board.king_sq[WHITE]
            bk = self.board.king_sq[BLACK]
            if wk is not None and bk is not None:
                dist = abs(file_of(wk) - file_of(bk)) + abs(rank_of(wk) - rank_of(bk))
                return (14 - dist) * 2
        return 0

    def move_score(self, move):
        frm, to, promo, flag = move
        piece = self.board.squares[frm]
        target = self.board.squares[to]
        score = 0
        if flag == "castle":
            score += 60
        if flag == "ep":
            score += 105
        if target is not None:
            score += 10 * PIECE_VALUES[target.upper()] - PIECE_VALUES[piece.upper()]
        if promo:
            score += PIECE_VALUES[promo.upper()] + 800
        hist = self.history[self.board.side][frm][to]
        score += hist
        if self.killer[0] and self.killer[0][0] == frm and self.killer[0][1] == to:
            score += 40
        if self.killer[1] and self.killer[1][0] == frm and self.killer[1][1] == to:
            score += 20
        return score

    def ordered_moves(self, moves):
        return sorted(moves, key=self.move_score, reverse=True)

    def qsearch(self, alpha, beta):
        if time.time() >= self.deadline:
            raise TimeoutError
        self.nodes += 1
        stand = self.evaluate()
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        moves = []
        for m in self.board.gen_pseudo():
            frm, to, promo, flag = m
            if flag == "castle":
                continue
            if promo or self.board.squares[to] is not None or flag == "ep":
                self.board.push(m)
                if not self.board.in_check(1 - self.board.side):
                    moves.append(m)
                self.board.pop()
        for m in self.ordered_moves(moves):
            self.board.push(m)
            score = -self.qsearch(-beta, -alpha)
            self.board.pop()
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def negamax(self, depth, alpha, beta, ply):
        if time.time() >= self.deadline:
            raise TimeoutError
        self.nodes += 1
        moves = self.board.legal_moves()
        if not moves:
            return -self.MATE + ply if self.board.in_check(self.board.side) else 0

        if depth <= 0:
            return self.evaluate()

        moves = self.ordered_moves(moves)

        best = -self.MATE
        best_move = None
        for idx, m in enumerate(moves):
            self.board.push(m)
            score = -self.negamax(depth - 1, -beta, -alpha, ply + 1)
            self.board.pop()
            if score > best:
                best = score
                best_move = m
            if score > alpha:
                alpha = score
            if alpha >= beta:
                if self.board.squares[m[1]] is None and m[2] is None and m[3] is None:
                    self.killer[ply % 64][1] = self.killer[ply % 64][0]
                    self.killer[ply % 64][0] = (m[0], m[1])
                break
            if time.time() >= self.deadline:
                raise TimeoutError

        if best_move is not None:
            if self.board.squares[best_move[1]] is None and best_move[2] is None and best_move[3] is None:
                self.history[self.board.side][best_move[0]][best_move[1]] += depth * depth
        return best

    def choose_move(self, movetime_ms):
        legal = self.board.legal_moves()
        if not legal:
            return "0000"
        if len(legal) == 1:
            return self.board.move_to_uci(legal[0])

        self.deadline = time.time() + max(0.001, movetime_ms / 1000.0 * 0.8)
        best_move = legal[0]
        best_score = -self.MATE
        for m in self.ordered_moves(legal):
            if time.time() >= self.deadline:
                break
            self.board.push(m)
            if not self.board.legal_moves():
                score = self.MATE - 1 if self.board.in_check(self.board.side) else 0
            else:
                score = -self.evaluate()
            self.board.pop()
            score += self.move_score(m) // 8
            if score > best_score:
                best_score = score
                best_move = m
        return self.board.move_to_uci(best_move)

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
                self.board.push_uci(tokens[i])
                i += 1


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
            print("bestmove", eng.choose_move(mt))
            sys.stdout.flush()
        elif line == "quit":
            break


if __name__ == "__main__":
    main()

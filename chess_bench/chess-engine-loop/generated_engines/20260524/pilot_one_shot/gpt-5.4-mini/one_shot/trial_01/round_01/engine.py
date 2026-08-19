#!/usr/bin/env python3
import sys
import time

WHITE = 0
BLACK = 1

PAWN = 1
KNIGHT = 2
BISHOP = 3
ROOK = 4
QUEEN = 5
KING = 6

FILES = "abcdefgh"
RANKS = "12345678"

PIECE_VALUES = {
    PAWN: 100,
    KNIGHT: 320,
    BISHOP: 330,
    ROOK: 500,
    QUEEN: 900,
    KING: 0,
}

FEN_PIECE_MAP = {
    "p": PAWN,
    "n": KNIGHT,
    "b": BISHOP,
    "r": ROOK,
    "q": QUEEN,
    "k": KING,
}

KNIGHT_DELTAS = (-17, -15, -10, -6, 6, 10, 15, 17)
KING_DELTAS = (-9, -8, -7, -1, 1, 7, 8, 9)


def sq_to_str(sq):
    return FILES[sq % 8] + RANKS[sq // 8]


def str_to_sq(text):
    return (ord(text[1]) - 49) * 8 + (ord(text[0]) - 97)


def on_board(sq):
    return 0 <= sq < 64


def file_of(sq):
    return sq & 7


def rank_of(sq):
    return sq >> 3


def color_of_piece(piece):
    return WHITE if piece > 0 else BLACK


def piece_type(piece):
    return abs(piece)


class Move:
    __slots__ = ("from_sq", "to_sq", "promo", "ep", "castle")

    def __init__(self, from_sq, to_sq, promo=0, ep=False, castle=False):
        self.from_sq = from_sq
        self.to_sq = to_sq
        self.promo = promo
        self.ep = ep
        self.castle = castle

    def uci(self):
        s = sq_to_str(self.from_sq) + sq_to_str(self.to_sq)
        if self.promo:
            s += "nbrq"[self.promo - 2]
        return s


class Board:
    def __init__(self):
        self.reset()

    def reset(self):
        self.squares = [0] * 64
        self.side = WHITE
        self.castling = 0
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = [4, 60]
        self.history = []
        self.set_fen("startpos")

    def set_fen(self, fen):
        if fen == "startpos":
            fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        parts = fen.split()
        board_part = parts[0]
        self.squares = [0] * 64
        r = 7
        f = 0
        for ch in board_part:
            if ch == "/":
                r -= 1
                f = 0
                continue
            if ch.isdigit():
                f += int(ch)
                continue
            sq = r * 8 + f
            piece = FEN_PIECE_MAP[ch.lower()]
            if ch.islower():
                piece = -piece
            self.squares[sq] = piece
            if abs(piece) == KING:
                self.king_sq[WHITE if piece > 0 else BLACK] = sq
            f += 1
        self.side = WHITE if parts[1] == "w" else BLACK
        self.castling = 0
        if "K" in parts[2]:
            self.castling |= 1
        if "Q" in parts[2]:
            self.castling |= 2
        if "k" in parts[2]:
            self.castling |= 4
        if "q" in parts[2]:
            self.castling |= 8
        self.ep = -1 if parts[3] == "-" else str_to_sq(parts[3])
        self.halfmove = int(parts[4])
        self.fullmove = int(parts[5])
        self.history = []

    def parse_position(self, tokens):
        if len(tokens) < 2:
            return
        if tokens[1] == "startpos":
            self.set_fen("startpos")
            move_start = 2
        else:
            fen = " ".join(tokens[2:8])
            self.set_fen(fen)
            move_start = 8
        for mv in tokens[move_start:]:
            legal = self.find_legal_move(mv)
            if legal is not None:
                self.push(legal)

    def is_attacked(self, sq, by_side):
        if by_side == WHITE:
            for d in (-7, -9):
                s = sq - d
                if on_board(s) and abs(file_of(s) - file_of(sq)) == 1 and self.squares[s] == PAWN:
                    return True
        else:
            for d in (7, 9):
                s = sq - d
                if on_board(s) and abs(file_of(s) - file_of(sq)) == 1 and self.squares[s] == -PAWN:
                    return True
        for d in KNIGHT_DELTAS:
            s = sq + d
            if not on_board(s):
                continue
            if abs(file_of(s) - file_of(sq)) > 2:
                continue
            p = self.squares[s]
            if p and color_of_piece(p) == by_side and abs(p) == KNIGHT:
                return True
        for d in (-9, -7, 7, 9):
            s = sq + d
            while on_board(s) and abs(file_of(s) - file_of(s - d)) == 1:
                p = self.squares[s]
                if p:
                    if color_of_piece(p) == by_side and abs(p) in (BISHOP, QUEEN):
                        return True
                    break
                s += d
        for d in (-8, -1, 1, 8):
            s = sq + d
            while on_board(s) and (d in (-1, 1) or file_of(s) == file_of(s - d)):
                p = self.squares[s]
                if p:
                    if color_of_piece(p) == by_side and abs(p) in (ROOK, QUEEN):
                        return True
                    break
                s += d
        for d in KING_DELTAS:
            s = sq + d
            if not on_board(s) or abs(file_of(s) - file_of(sq)) > 1:
                continue
            p = self.squares[s]
            if p and color_of_piece(p) == by_side and abs(p) == KING:
                return True
        return False

    def in_check(self, side):
        return self.is_attacked(self.king_sq[side], 1 - side)

    def push(self, move):
        piece = self.squares[move.from_sq]
        captured = self.squares[move.to_sq]
        state = (move, captured, self.castling, self.ep, self.halfmove, self.fullmove, self.king_sq[0], self.king_sq[1])
        self.history.append(state)
        self.ep = -1
        self.halfmove += 1
        if abs(piece) == PAWN or captured:
            self.halfmove = 0
        self.squares[move.from_sq] = 0
        if move.ep:
            cap_sq = move.to_sq - 8 if self.side == WHITE else move.to_sq + 8
            captured = self.squares[cap_sq]
            self.squares[cap_sq] = 0
        if move.castle:
            if move.to_sq == 6:
                self.squares[5] = self.squares[7]
                self.squares[7] = 0
            elif move.to_sq == 2:
                self.squares[3] = self.squares[0]
                self.squares[0] = 0
            elif move.to_sq == 62:
                self.squares[61] = self.squares[63]
                self.squares[63] = 0
            elif move.to_sq == 58:
                self.squares[59] = self.squares[56]
                self.squares[56] = 0
        placed = piece
        if move.promo:
            placed = move.promo if piece > 0 else -move.promo
        self.squares[move.to_sq] = placed
        if abs(piece) == KING:
            self.king_sq[self.side] = move.to_sq
            if self.side == WHITE:
                self.castling &= ~3
            else:
                self.castling &= ~12
        if abs(piece) == ROOK:
            if move.from_sq == 0:
                self.castling &= ~2
            elif move.from_sq == 7:
                self.castling &= ~1
            elif move.from_sq == 56:
                self.castling &= ~8
            elif move.from_sq == 63:
                self.castling &= ~4
        if captured and abs(captured) == ROOK:
            if move.to_sq == 0:
                self.castling &= ~2
            elif move.to_sq == 7:
                self.castling &= ~1
            elif move.to_sq == 56:
                self.castling &= ~8
            elif move.to_sq == 63:
                self.castling &= ~4
        if abs(piece) == PAWN and abs(move.to_sq - move.from_sq) == 16:
            self.ep = (move.from_sq + move.to_sq) // 2
        if self.side == BLACK:
            self.fullmove += 1
        self.side = 1 - self.side

    def pop(self):
        move, captured, castling, ep, halfmove, fullmove, k0, k1 = self.history.pop()
        self.side = 1 - self.side
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.fullmove = fullmove
        self.king_sq[0] = k0
        self.king_sq[1] = k1
        piece = self.squares[move.to_sq]
        if move.castle:
            if move.to_sq == 6:
                self.squares[7] = self.squares[5]
                self.squares[5] = 0
            elif move.to_sq == 2:
                self.squares[0] = self.squares[3]
                self.squares[3] = 0
            elif move.to_sq == 62:
                self.squares[63] = self.squares[61]
                self.squares[61] = 0
            elif move.to_sq == 58:
                self.squares[56] = self.squares[59]
                self.squares[59] = 0
        self.squares[move.from_sq] = self.squares[move.to_sq]
        if move.promo:
            self.squares[move.from_sq] = PAWN if self.side == WHITE else -PAWN
        self.squares[move.to_sq] = captured
        if move.ep:
            cap_sq = move.to_sq - 8 if self.side == WHITE else move.to_sq + 8
            self.squares[cap_sq] = -PAWN if self.side == WHITE else PAWN

    def pseudo_moves(self):
        side = self.side
        forward = 8 if side == WHITE else -8
        start_rank = 1 if side == WHITE else 6
        promo_rank = 6 if side == WHITE else 1
        enemy = BLACK if side == WHITE else WHITE
        for sq, p in enumerate(self.squares):
            if not p or color_of_piece(p) != side:
                continue
            t = abs(p)
            if t == PAWN:
                one = sq + forward
                if on_board(one) and self.squares[one] == 0:
                    if rank_of(sq) == promo_rank:
                        for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                            yield Move(sq, one, promo=promo)
                    else:
                        yield Move(sq, one)
                    two = sq + 2 * forward
                    if rank_of(sq) == start_rank and self.squares[two] == 0:
                        yield Move(sq, two)
                for cap_delta in (forward - 1, forward + 1):
                    to = sq + cap_delta
                    if not on_board(to) or abs(file_of(to) - file_of(sq)) != 1:
                        continue
                    target = self.squares[to]
                    if target and color_of_piece(target) == enemy:
                        if rank_of(sq) == promo_rank:
                            for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                                yield Move(sq, to, promo=promo)
                        else:
                            yield Move(sq, to)
                    elif to == self.ep:
                        yield Move(sq, to, ep=True)
            elif t == KNIGHT:
                for d in KNIGHT_DELTAS:
                    to = sq + d
                    if not on_board(to) or abs(file_of(to) - file_of(sq)) > 2:
                        continue
                    target = self.squares[to]
                    if not target or color_of_piece(target) == enemy:
                        yield Move(sq, to)
            elif t in (BISHOP, ROOK, QUEEN):
                dirs = []
                if t in (BISHOP, QUEEN):
                    dirs += (-9, -7, 7, 9)
                if t in (ROOK, QUEEN):
                    dirs += (-8, -1, 1, 8)
                for d in dirs:
                    to = sq + d
                    while on_board(to) and (d in (-1, 1) or abs(file_of(to) - file_of(to - d)) == 1 if d in (-9, -7, 7, 9) else file_of(to) == file_of(to - d)):
                        target = self.squares[to]
                        if not target:
                            yield Move(sq, to)
                        else:
                            if color_of_piece(target) == enemy:
                                yield Move(sq, to)
                            break
                        to += d
            else:
                for d in KING_DELTAS:
                    to = sq + d
                    if not on_board(to) or abs(file_of(to) - file_of(sq)) > 1:
                        continue
                    target = self.squares[to]
                    if not target or color_of_piece(target) == enemy:
                        yield Move(sq, to)
                if side == WHITE and sq == 4:
                    if (self.castling & 1) and self.squares[5] == 0 and self.squares[6] == 0 and not self.in_check(side) and not self.is_attacked(5, enemy) and not self.is_attacked(6, enemy):
                        yield Move(4, 6, castle=True)
                    if (self.castling & 2) and self.squares[1] == 0 and self.squares[2] == 0 and self.squares[3] == 0 and not self.in_check(side) and not self.is_attacked(3, enemy) and not self.is_attacked(2, enemy):
                        yield Move(4, 2, castle=True)
                elif side == BLACK and sq == 60:
                    if (self.castling & 4) and self.squares[61] == 0 and self.squares[62] == 0 and not self.in_check(side) and not self.is_attacked(61, enemy) and not self.is_attacked(62, enemy):
                        yield Move(60, 62, castle=True)
                    if (self.castling & 8) and self.squares[57] == 0 and self.squares[58] == 0 and self.squares[59] == 0 and not self.in_check(side) and not self.is_attacked(59, enemy) and not self.is_attacked(58, enemy):
                        yield Move(60, 58, castle=True)

    def legal_moves(self):
        for mv in self.pseudo_moves():
            self.push(mv)
            ok = not self.in_check(1 - self.side)
            self.pop()
            if ok:
                yield mv

    def find_legal_move(self, uci):
        for mv in self.legal_moves():
            if mv.uci() == uci:
                return mv
        return None

    def evaluate(self):
        score = 0
        for sq, p in enumerate(self.squares):
            if not p:
                continue
            val = PIECE_VALUES[abs(p)]
            if abs(p) == PAWN:
                r = rank_of(sq)
                adv = r if p > 0 else 7 - r
                val += adv * 6
            elif abs(p) == KNIGHT:
                val += [0, 5, 10, 15, 15, 10, 5, 0][file_of(sq)]
            elif abs(p) == BISHOP:
                val += 5 if (file_of(sq) + rank_of(sq)) % 2 == 0 else 0
            score += val if p > 0 else -val
        side_moves = sum(1 for _ in self.legal_moves())
        mobility = min(side_moves, 20) * 2
        score += mobility if self.side == WHITE else -mobility
        if self.in_check(self.side):
            score -= 18 if self.side == WHITE else -18
        return score if self.side == WHITE else -score


class Search:
    def __init__(self, board):
        self.board = board
        self.deadline = 0
        self.nodes = 0
        self.best = None

    def time_up(self):
        return time.monotonic() >= self.deadline

    def quiescence(self, alpha, beta):
        if self.time_up():
            raise TimeoutError
        self.nodes += 1
        stand = self.board.evaluate()
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        for mv in self.board.legal_moves():
            if self.board.squares[mv.to_sq] == 0 and not mv.ep:
                continue
            self.board.push(mv)
            score = -self.quiescence(-beta, -alpha)
            self.board.pop()
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def order_moves(self, moves):
        scored = []
        for mv in moves:
            target = self.board.squares[mv.to_sq]
            score = 0
            if mv.promo:
                score += 800 + PIECE_VALUES[mv.promo]
            if target:
                score += 10 * PIECE_VALUES[abs(target)] - PIECE_VALUES[abs(self.board.squares[mv.from_sq])]
            if mv.castle:
                score += 40
            if mv.ep:
                score += 105
            scored.append((score, mv))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [mv for _, mv in scored]

    def negamax(self, depth, alpha, beta):
        if self.time_up():
            raise TimeoutError
        self.nodes += 1
        if depth == 0:
            return self.quiescence(alpha, beta)
        moves = list(self.board.legal_moves())
        if not moves:
            return -100000 + (4 - depth) if self.board.in_check(self.board.side) else 0
        best = -10**9
        for mv in self.order_moves(moves):
            self.board.push(mv)
            score = -self.negamax(depth - 1, -beta, -alpha)
            self.board.pop()
            if score > best:
                best = score
            if score > alpha:
                alpha = score
                if depth == self.root_depth:
                    self.best = mv
            if alpha >= beta:
                break
        return best

    def choose(self, movetime_ms):
        self.deadline = time.monotonic() + max(0.01, movetime_ms / 1000.0 - 0.002)
        self.best = None
        legal = list(self.board.legal_moves())
        if not legal:
            return "0000"
        self.best = legal[0]
        depth = 1
        try:
            while True:
                self.root_depth = depth
                self.negamax(depth, -10**9, 10**9)
                depth += 1
        except TimeoutError:
            pass
        return self.best.uci() if self.best else legal[0].uci()


def main():
    board = Board()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        cmd = tokens[0]
        if cmd == "uci":
            print("id name MinimalPythonEngine")
            print("id author openai")
            print("uciok")
            sys.stdout.flush()
        elif cmd == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            board.reset()
        elif cmd == "position":
            board.parse_position(tokens)
        elif cmd == "go":
            movetime = 20
            if "movetime" in tokens:
                i = tokens.index("movetime")
                if i + 1 < len(tokens):
                    try:
                        movetime = int(tokens[i + 1])
                    except ValueError:
                        movetime = 20
            best = Search(board).choose(movetime)
            print(f"bestmove {best}")
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

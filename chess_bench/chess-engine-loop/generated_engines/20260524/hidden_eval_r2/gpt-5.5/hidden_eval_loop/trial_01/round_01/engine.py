#!/usr/bin/env python3
import sys
import time

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FILES = "abcdefgh"
RANKS = "12345678"
PIECE_VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
MATE = 100000

KNIGHT_DELTAS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_DELTAS = ((1, 1), (1, 0), (1, -1), (0, 1), (0, -1), (-1, 1), (-1, 0), (-1, -1))
BISHOP_DELTAS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ROOK_DELTAS = ((1, 0), (-1, 0), (0, 1), (0, -1))
QUEEN_DELTAS = BISHOP_DELTAS + ROOK_DELTAS


def idx(file_index, rank_index):
    return rank_index * 8 + file_index


def file_of(square):
    return square & 7


def rank_of(square):
    return square >> 3


def on_board(file_index, rank_index):
    return 0 <= file_index < 8 and 0 <= rank_index < 8


def square_name(square):
    return FILES[file_of(square)] + RANKS[rank_of(square)]


def parse_square(text):
    if len(text) != 2 or text[0] not in FILES or text[1] not in RANKS:
        return None
    return idx(FILES.index(text[0]), RANKS.index(text[1]))


def color_of(piece):
    if piece == ".":
        return None
    return "w" if piece.isupper() else "b"


def enemy(color):
    return "b" if color == "w" else "w"


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
    __slots__ = ("board", "turn", "castling", "ep", "halfmove", "fullmove")

    def __init__(self, board=None, turn="w", castling="", ep=None, halfmove=0, fullmove=1):
        self.board = board if board is not None else ["."] * 64
        self.turn = turn
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.fullmove = fullmove

    @classmethod
    def from_fen(cls, fen):
        try:
            parts = fen.strip().split()
            if len(parts) < 4:
                raise ValueError
            board = ["."] * 64
            ranks = parts[0].split("/")
            if len(ranks) != 8:
                raise ValueError
            for fen_rank, row in enumerate(ranks):
                rank_index = 7 - fen_rank
                file_index = 0
                for ch in row:
                    if ch.isdigit():
                        file_index += int(ch)
                    elif ch in "PNBRQKpnbrqk" and file_index < 8:
                        board[idx(file_index, rank_index)] = ch
                        file_index += 1
                    else:
                        raise ValueError
                if file_index != 8:
                    raise ValueError
            turn = parts[1] if parts[1] in ("w", "b") else "w"
            castling = "" if parts[2] == "-" else "".join(c for c in parts[2] if c in "KQkq")
            ep = None if parts[3] == "-" else parse_square(parts[3])
            halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
            return cls(board, turn, castling, ep, halfmove, fullmove)
        except Exception:
            return cls.from_fen(START_FEN)

    def clone(self):
        return Position(self.board[:], self.turn, self.castling, self.ep, self.halfmove, self.fullmove)

    def king_square(self, color):
        target = "K" if color == "w" else "k"
        for i, piece in enumerate(self.board):
            if piece == target:
                return i
        return None

    def is_attacked(self, square, by_color):
        b = self.board
        f = file_of(square)
        r = rank_of(square)
        pawn = "P" if by_color == "w" else "p"
        pawn_rank_delta = -1 if by_color == "w" else 1
        for df in (-1, 1):
            nf, nr = f + df, r + pawn_rank_delta
            if on_board(nf, nr) and b[idx(nf, nr)] == pawn:
                return True
        knight = "N" if by_color == "w" else "n"
        for df, dr in KNIGHT_DELTAS:
            nf, nr = f + df, r + dr
            if on_board(nf, nr) and b[idx(nf, nr)] == knight:
                return True
        bishop = "B" if by_color == "w" else "b"
        rook = "R" if by_color == "w" else "r"
        queen = "Q" if by_color == "w" else "q"
        king = "K" if by_color == "w" else "k"
        for df, dr in BISHOP_DELTAS:
            nf, nr = f + df, r + dr
            while on_board(nf, nr):
                piece = b[idx(nf, nr)]
                if piece != ".":
                    if piece == bishop or piece == queen:
                        return True
                    break
                nf += df
                nr += dr
        for df, dr in ROOK_DELTAS:
            nf, nr = f + df, r + dr
            while on_board(nf, nr):
                piece = b[idx(nf, nr)]
                if piece != ".":
                    if piece == rook or piece == queen:
                        return True
                    break
                nf += df
                nr += dr
        for df, dr in KING_DELTAS:
            nf, nr = f + df, r + dr
            if on_board(nf, nr) and b[idx(nf, nr)] == king:
                return True
        return False

    def in_check(self, color):
        king = self.king_square(color)
        return king is None or self.is_attacked(king, enemy(color))

    def pseudo_moves(self):
        color = self.turn
        own = str.isupper if color == "w" else str.islower
        forward = 1 if color == "w" else -1
        start_rank = 1 if color == "w" else 6
        promo_rank = 7 if color == "w" else 0
        moves = []
        b = self.board
        for sq, piece in enumerate(b):
            if piece == "." or color_of(piece) != color:
                continue
            f, r = file_of(sq), rank_of(sq)
            p = piece.upper()
            if p == "P":
                nr = r + forward
                if on_board(f, nr):
                    to = idx(f, nr)
                    if b[to] == ".":
                        if nr == promo_rank:
                            for pr in "qrbn":
                                moves.append(Move(sq, to, pr))
                        else:
                            moves.append(Move(sq, to))
                            if r == start_rank:
                                two = idx(f, r + 2 * forward)
                                if b[two] == ".":
                                    moves.append(Move(sq, two))
                    for df in (-1, 1):
                        nf = f + df
                        if on_board(nf, nr):
                            cap = idx(nf, nr)
                            target = b[cap]
                            if target != "." and not own(target):
                                if nr == promo_rank:
                                    for pr in "qrbn":
                                        moves.append(Move(sq, cap, pr))
                                else:
                                    moves.append(Move(sq, cap))
                            elif self.ep is not None and cap == self.ep:
                                moves.append(Move(sq, cap, ep=True))
            elif p == "N":
                for df, dr in KNIGHT_DELTAS:
                    nf, nr = f + df, r + dr
                    if on_board(nf, nr):
                        to = idx(nf, nr)
                        if b[to] == "." or not own(b[to]):
                            moves.append(Move(sq, to))
            elif p in ("B", "R", "Q"):
                deltas = BISHOP_DELTAS if p == "B" else ROOK_DELTAS if p == "R" else QUEEN_DELTAS
                for df, dr in deltas:
                    nf, nr = f + df, r + dr
                    while on_board(nf, nr):
                        to = idx(nf, nr)
                        if b[to] == ".":
                            moves.append(Move(sq, to))
                        else:
                            if not own(b[to]):
                                moves.append(Move(sq, to))
                            break
                        nf += df
                        nr += dr
            elif p == "K":
                for df, dr in KING_DELTAS:
                    nf, nr = f + df, r + dr
                    if on_board(nf, nr):
                        to = idx(nf, nr)
                        if b[to] == "." or not own(b[to]):
                            moves.append(Move(sq, to))
                if color == "w" and sq == parse_square("e1") and not self.in_check("w"):
                    if "K" in self.castling and b[parse_square("f1")] == "." and b[parse_square("g1")] == ".":
                        if not self.is_attacked(parse_square("f1"), "b") and not self.is_attacked(parse_square("g1"), "b"):
                            moves.append(Move(sq, parse_square("g1"), castle=True))
                    if "Q" in self.castling and b[parse_square("d1")] == "." and b[parse_square("c1")] == "." and b[parse_square("b1")] == ".":
                        if not self.is_attacked(parse_square("d1"), "b") and not self.is_attacked(parse_square("c1"), "b"):
                            moves.append(Move(sq, parse_square("c1"), castle=True))
                if color == "b" and sq == parse_square("e8") and not self.in_check("b"):
                    if "k" in self.castling and b[parse_square("f8")] == "." and b[parse_square("g8")] == ".":
                        if not self.is_attacked(parse_square("f8"), "w") and not self.is_attacked(parse_square("g8"), "w"):
                            moves.append(Move(sq, parse_square("g8"), castle=True))
                    if "q" in self.castling and b[parse_square("d8")] == "." and b[parse_square("c8")] == "." and b[parse_square("b8")] == ".":
                        if not self.is_attacked(parse_square("d8"), "w") and not self.is_attacked(parse_square("c8"), "w"):
                            moves.append(Move(sq, parse_square("c8"), castle=True))
        return moves

    def legal_moves(self):
        color = self.turn
        out = []
        for move in self.pseudo_moves():
            child = self.make_move(move)
            if not child.in_check(color):
                out.append(move)
        return out

    def make_move(self, move):
        pos = self.clone()
        b = pos.board
        piece = b[move.frm]
        captured = b[move.to]
        b[move.frm] = "."
        if move.ep:
            cap_sq = move.to - 8 if self.turn == "w" else move.to + 8
            captured = b[cap_sq]
            b[cap_sq] = "."
        put = piece
        if move.promo:
            put = move.promo.upper() if self.turn == "w" else move.promo.lower()
        b[move.to] = put
        if move.castle:
            if move.to == parse_square("g1"):
                b[parse_square("h1")] = "."
                b[parse_square("f1")] = "R"
            elif move.to == parse_square("c1"):
                b[parse_square("a1")] = "."
                b[parse_square("d1")] = "R"
            elif move.to == parse_square("g8"):
                b[parse_square("h8")] = "."
                b[parse_square("f8")] = "r"
            elif move.to == parse_square("c8"):
                b[parse_square("a8")] = "."
                b[parse_square("d8")] = "r"
        castling = pos.castling
        for flag, square in (("K", "e1"), ("Q", "e1"), ("k", "e8"), ("q", "e8")):
            if move.frm == parse_square(square):
                castling = castling.replace(flag, "")
        rook_flags = {
            parse_square("h1"): "K",
            parse_square("a1"): "Q",
            parse_square("h8"): "k",
            parse_square("a8"): "q",
        }
        if move.frm in rook_flags:
            castling = castling.replace(rook_flags[move.frm], "")
        if move.to in rook_flags and captured != ".":
            castling = castling.replace(rook_flags[move.to], "")
        pos.castling = castling
        pos.ep = None
        if piece.upper() == "P" and abs(move.to - move.frm) == 16:
            pos.ep = (move.to + move.frm) // 2
        pos.halfmove = 0 if piece.upper() == "P" or captured != "." else pos.halfmove + 1
        if self.turn == "b":
            pos.fullmove += 1
        pos.turn = enemy(self.turn)
        return pos


def piece_square(piece, square):
    f = file_of(square)
    r = rank_of(square)
    center = 6 - (abs(f - 3.5) + abs(r - 3.5))
    p = piece.upper()
    if p == "P":
        advance = r if piece.isupper() else 7 - r
        return advance * 8 - abs(f - 3.5) * 2
    if p in ("N", "B"):
        return center * 8
    if p == "R":
        return (r if piece.isupper() else 7 - r) * 2
    if p == "Q":
        return center * 2
    if p == "K":
        home = 7 - r if piece.isupper() else r
        return home * 5 - center * 3
    return 0


def evaluate(pos):
    score = 0
    for sq, piece in enumerate(pos.board):
        if piece == ".":
            continue
        val = PIECE_VALUE[piece.upper()] + piece_square(piece, sq)
        score += val if piece.isupper() else -val
    wk = pos.king_square("w")
    bk = pos.king_square("b")
    if wk is not None and pos.is_attacked(wk, "b"):
        score -= 35
    if bk is not None and pos.is_attacked(bk, "w"):
        score += 35
    return score if pos.turn == "w" else -score


def move_score(pos, move):
    piece = pos.board[move.frm]
    target = pos.board[move.to]
    score = 0
    if target != ".":
        score += 10 * PIECE_VALUE[target.upper()] - PIECE_VALUE[piece.upper()]
    if move.promo:
        score += PIECE_VALUE[move.promo.upper()]
    if move.castle:
        score += 40
    center_to = abs(file_of(move.to) - 3.5) + abs(rank_of(move.to) - 3.5)
    score += int(8 - center_to)
    return score


class SearchTimeout(Exception):
    pass


class Engine:
    def __init__(self):
        self.pos = Position.from_fen(START_FEN)
        self.deadline = 0.0
        self.nodes = 0

    def set_position(self, tokens):
        try:
            if not tokens:
                return
            moves_start = None
            if tokens[0] == "startpos":
                self.pos = Position.from_fen(START_FEN)
                moves_start = 1
            elif tokens[0] == "fen" and len(tokens) >= 7:
                self.pos = Position.from_fen(" ".join(tokens[1:7]))
                moves_start = 7
            else:
                return
            if moves_start < len(tokens) and tokens[moves_start] == "moves":
                for uci in tokens[moves_start + 1:]:
                    self.apply_uci(uci)
        except Exception:
            self.pos = Position.from_fen(START_FEN)

    def apply_uci(self, text):
        for move in self.pos.legal_moves():
            if move.uci() == text:
                self.pos = self.pos.make_move(move)
                return True
        return False

    def search_best(self, movetime_ms):
        legal = self.pos.legal_moves()
        if not legal:
            return "0000"
        ordered = sorted(legal, key=lambda m: move_score(self.pos, m), reverse=True)
        best = ordered[0]
        budget = max(0.005, min(1.0, movetime_ms / 1000.0) * 0.82)
        self.deadline = time.monotonic() + budget
        self.nodes = 0
        depth = 1
        try:
            while depth <= 5:
                alpha = -MATE
                local_best = best
                for move in ordered:
                    self.check_time()
                    score = -self.alphabeta(self.pos.make_move(move), depth - 1, -MATE, -alpha)
                    if score > alpha:
                        alpha = score
                        local_best = move
                best = local_best
                depth += 1
                if time.monotonic() > self.deadline - 0.002:
                    break
        except SearchTimeout:
            pass
        return best.uci()

    def check_time(self):
        self.nodes += 1
        if self.nodes & 255 == 0 and time.monotonic() >= self.deadline:
            raise SearchTimeout

    def alphabeta(self, pos, depth, alpha, beta):
        self.check_time()
        legal = pos.legal_moves()
        if depth <= 0:
            return self.quiesce(pos, alpha, beta, 0)
        if not legal:
            return -MATE + depth if pos.in_check(pos.turn) else 0
        ordered = sorted(legal, key=lambda m: move_score(pos, m), reverse=True)
        for move in ordered:
            score = -self.alphabeta(pos.make_move(move), depth - 1, -beta, -alpha)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def quiesce(self, pos, alpha, beta, ply):
        self.check_time()
        stand = evaluate(pos)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        if ply >= 2:
            return alpha
        captures = []
        for move in pos.legal_moves():
            if pos.board[move.to] != "." or move.ep or move.promo:
                captures.append(move)
        captures.sort(key=lambda m: move_score(pos, m), reverse=True)
        for move in captures:
            score = -self.quiesce(pos.make_move(move), -beta, -alpha, ply + 1)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha


def parse_movetime(tokens):
    if "movetime" in tokens:
        i = tokens.index("movetime")
        if i + 1 < len(tokens):
            try:
                return max(1, int(tokens[i + 1]))
            except ValueError:
                pass
    return 20


def main():
    engine = Engine()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        cmd = tokens[0]
        try:
            if cmd == "uci":
                print("id name ScratchPy 1")
                print("id author OpenAI")
                print("uciok")
                sys.stdout.flush()
            elif cmd == "isready":
                print("readyok")
                sys.stdout.flush()
            elif cmd == "ucinewgame":
                engine.pos = Position.from_fen(START_FEN)
            elif cmd == "position":
                engine.set_position(tokens[1:])
            elif cmd == "go":
                print("bestmove " + engine.search_best(parse_movetime(tokens[1:])))
                sys.stdout.flush()
            elif cmd == "quit":
                break
        except Exception:
            if cmd == "go":
                print("bestmove 0000")
                sys.stdout.flush()


if __name__ == "__main__":
    main()

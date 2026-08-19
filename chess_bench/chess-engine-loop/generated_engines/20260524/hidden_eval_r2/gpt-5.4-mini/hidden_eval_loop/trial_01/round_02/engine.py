import sys
import time


FILES = "abcdefgh"
RANKS = "12345678"

WHITE, BLACK = 0, 1

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = "PNBRQK"
PIECE_VALUES = {
    PAWN: 100,
    KNIGHT: 320,
    BISHOP: 330,
    ROOK: 500,
    QUEEN: 900,
    KING: 0,
}

KNIGHT_DELTAS = (-17, -15, -10, -6, 6, 10, 15, 17)
BISHOP_DELTAS = (-9, -7, 7, 9)
ROOK_DELTAS = (-8, -1, 1, 8)
KING_DELTAS = (-9, -8, -7, -1, 1, 7, 8, 9)


def sq_to_str(sq):
    return FILES[sq % 8] + RANKS[sq // 8]


def str_to_sq(s):
    return (int(s[1]) - 1) * 8 + FILES.index(s[0])


def in_bounds(sq):
    return 0 <= sq < 64


def file_of(sq):
    return sq & 7


def rank_of(sq):
    return sq >> 3


def color_of(piece):
    return WHITE if piece.isupper() else BLACK


def piece_type(piece):
    return piece.upper()


class Position:
    def __init__(self):
        self.board = [None] * 64
        self.side = WHITE
        self.castling = "-"
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = {WHITE: 4, BLACK: 60}
        self.history = []

    def set_startpos(self):
        self.set_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def set_fen(self, fen):
        parts = fen.split()
        board_part = parts[0]
        self.board = [None] * 64
        r = 7
        f = 0
        for ch in board_part:
            if ch == "/":
                r -= 1
                f = 0
            elif ch.isdigit():
                f += int(ch)
            else:
                sq = r * 8 + f
                self.board[sq] = ch
                if ch.upper() == KING:
                    self.king_sq[color_of(ch)] = sq
                f += 1
        self.side = WHITE if parts[1] == "w" else BLACK
        self.castling = parts[2]
        self.ep = None if parts[3] == "-" else str_to_sq(parts[3])
        self.halfmove = int(parts[4])
        self.fullmove = int(parts[5])
        self.history = []

    def parse_position(self, tokens):
        if tokens[1] == "startpos":
            self.set_startpos()
            move_tokens = tokens[2:]
        else:
            fen = " ".join(tokens[2:8])
            self.set_fen(fen)
            move_tokens = tokens[8:]
        for mv in move_tokens:
            self.push_uci(mv)

    def enemy(self):
        return BLACK if self.side == WHITE else WHITE

    def push_uci(self, uci):
        moves = self.legal_moves()
        for mv in moves:
            if mv.uci() == uci:
                self.make_move(mv)
                return

    def make_move(self, mv):
        state = (mv, self.board[mv.from_sq], self.board[mv.to_sq], self.castling, self.ep, self.halfmove, self.fullmove, self.king_sq[WHITE], self.king_sq[BLACK], self.side)
        self.history.append(state)
        piece = self.board[mv.from_sq]
        captured = self.board[mv.to_sq]
        self.board[mv.from_sq] = None
        if mv.ep_capture is not None:
            captured = self.board[mv.ep_capture]
            self.board[mv.ep_capture] = None
        if mv.castle:
            if mv.to_sq == 6:
                self.board[5] = self.board[7]
                self.board[7] = None
            elif mv.to_sq == 2:
                self.board[3] = self.board[0]
                self.board[0] = None
            elif mv.to_sq == 62:
                self.board[61] = self.board[63]
                self.board[63] = None
            elif mv.to_sq == 58:
                self.board[59] = self.board[56]
                self.board[56] = None
        placed = mv.promotion if mv.promotion else piece
        self.board[mv.to_sq] = placed
        if piece.upper() == KING:
            self.king_sq[color_of(piece)] = mv.to_sq
            if color_of(piece) == WHITE:
                self.castling = self.castling.replace("K", "").replace("Q", "")
            else:
                self.castling = self.castling.replace("k", "").replace("q", "")
        if mv.from_sq == 0 or mv.to_sq == 0:
            self.castling = self.castling.replace("Q", "")
        if mv.from_sq == 7 or mv.to_sq == 7:
            self.castling = self.castling.replace("K", "")
        if mv.from_sq == 56 or mv.to_sq == 56:
            self.castling = self.castling.replace("q", "")
        if mv.from_sq == 63 or mv.to_sq == 63:
            self.castling = self.castling.replace("k", "")
        self.castling = self.castling or "-"
        self.ep = None
        if piece.upper() == PAWN and abs(mv.to_sq - mv.from_sq) == 16:
            self.ep = (mv.to_sq + mv.from_sq) // 2
        self.halfmove = 0 if piece.upper() == PAWN or captured is not None else self.halfmove + 1
        if self.side == BLACK:
            self.fullmove += 1
        self.side ^= 1

    def unmake(self):
        mv, from_piece, to_piece, castling, ep, halfmove, fullmove, wk, bk, side = self.history.pop()
        self.side = side
        self.board[mv.from_sq] = from_piece
        self.board[mv.to_sq] = to_piece
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.fullmove = fullmove
        self.king_sq[WHITE] = wk
        self.king_sq[BLACK] = bk
        if mv.ep_capture is not None:
            self.board[mv.ep_capture] = "p" if side == WHITE else "P"
        if mv.castle:
            if mv.to_sq == 6:
                self.board[7] = self.board[5]
                self.board[5] = None
            elif mv.to_sq == 2:
                self.board[0] = self.board[3]
                self.board[3] = None
            elif mv.to_sq == 62:
                self.board[63] = self.board[61]
                self.board[61] = None
            elif mv.to_sq == 58:
                self.board[56] = self.board[59]
                self.board[59] = None

    def king_in_check(self, color):
        return self.attacked(self.king_sq[color], color ^ 1)

    def attacked(self, sq, by_color):
        step = 8 if by_color == WHITE else -8
        for d in (-1, 1):
            tsq = sq - step + d
            if in_bounds(tsq) and abs(file_of(tsq) - file_of(sq)) == 1:
                p = self.board[tsq]
                if p == ("P" if by_color == WHITE else "p"):
                    return True
        for d in KNIGHT_DELTAS:
            tsq = sq + d
            if in_bounds(tsq) and abs(file_of(tsq) - file_of(sq)) <= 2:
                p = self.board[tsq]
                if p == ("N" if by_color == WHITE else "n"):
                    return True
        for d in BISHOP_DELTAS:
            tsq = sq + d
            while in_bounds(tsq) and abs(file_of(tsq) - file_of(tsq - d)) == 1:
                p = self.board[tsq]
                if p is not None:
                    if color_of(p) == by_color and piece_type(p) in (BISHOP, QUEEN):
                        return True
                    break
                tsq += d
        for d in ROOK_DELTAS:
            tsq = sq + d
            while in_bounds(tsq) and (d in (-1, 1) and rank_of(tsq) == rank_of(tsq - d) or d in (-8, 8)):
                p = self.board[tsq]
                if p is not None:
                    if color_of(p) == by_color and piece_type(p) in (ROOK, QUEEN):
                        return True
                    break
                tsq += d
        for d in KING_DELTAS:
            tsq = sq + d
            if in_bounds(tsq) and max(abs(file_of(tsq) - file_of(sq)), abs(rank_of(tsq) - rank_of(sq))) == 1:
                p = self.board[tsq]
                if p == ("K" if by_color == WHITE else "k"):
                    return True
        return False

    def legal_moves(self):
        moves = self.pseudo_legal_moves()
        legal = []
        for mv in moves:
            self.make_move(mv)
            if not self.king_in_check(self.side ^ 1):
                legal.append(mv)
            self.unmake()
        return legal

    def pseudo_legal_moves(self):
        moves = []
        for sq, p in enumerate(self.board):
            if p is None or color_of(p) != self.side:
                continue
            pt = piece_type(p)
            if pt == PAWN:
                self.gen_pawn_moves(sq, p, moves)
            elif pt == KNIGHT:
                self.gen_leaper_moves(sq, p, KNIGHT_DELTAS, moves)
            elif pt == BISHOP:
                self.gen_slider_moves(sq, p, BISHOP_DELTAS, moves)
            elif pt == ROOK:
                self.gen_slider_moves(sq, p, ROOK_DELTAS, moves)
            elif pt == QUEEN:
                self.gen_slider_moves(sq, p, BISHOP_DELTAS + ROOK_DELTAS, moves)
            elif pt == KING:
                self.gen_king_moves(sq, p, moves)
        return moves

    def gen_leaper_moves(self, sq, p, deltas, moves):
        for d in deltas:
            tsq = sq + d
            if not in_bounds(tsq):
                continue
            if abs(file_of(tsq) - file_of(sq)) > 2:
                continue
            t = self.board[tsq]
            if t is None or color_of(t) != self.side:
                moves.append(Move(sq, tsq, p, t))

    def gen_slider_moves(self, sq, p, deltas, moves):
        for d in deltas:
            tsq = sq + d
            while in_bounds(tsq) and (d in (-1, 1) and rank_of(tsq) == rank_of(tsq - d) or d in (-8, 8) or abs(file_of(tsq) - file_of(tsq - d)) == 1):
                t = self.board[tsq]
                if t is None:
                    moves.append(Move(sq, tsq, p, None))
                else:
                    if color_of(t) != self.side:
                        moves.append(Move(sq, tsq, p, t))
                    break
                tsq += d

    def gen_pawn_moves(self, sq, p, moves):
        direction = 8 if self.side == WHITE else -8
        start_rank = 1 if self.side == WHITE else 6
        promo_rank = 6 if self.side == WHITE else 1
        one = sq + direction
        if in_bounds(one) and self.board[one] is None:
            if rank_of(sq) == promo_rank:
                for pr in "QRBN":
                    moves.append(Move(sq, one, p, None, promotion=pr if self.side == WHITE else pr.lower()))
            else:
                moves.append(Move(sq, one, p, None))
                two = sq + 2 * direction
                if rank_of(sq) == start_rank and self.board[two] is None:
                    moves.append(Move(sq, two, p, None))
        for cap in (direction - 1, direction + 1):
            tsq = sq + cap
            if not in_bounds(tsq) or abs(file_of(tsq) - file_of(sq)) != 1:
                continue
            t = self.board[tsq]
            if t is not None and color_of(t) != self.side:
                if rank_of(sq) == promo_rank:
                    for pr in "QRBN":
                        moves.append(Move(sq, tsq, p, t, promotion=pr if self.side == WHITE else pr.lower()))
                else:
                    moves.append(Move(sq, tsq, p, t))
            if self.ep == tsq:
                cap_sq = tsq - direction
                moves.append(Move(sq, tsq, p, None, ep_capture=cap_sq))

    def gen_king_moves(self, sq, p, moves):
        for d in KING_DELTAS:
            tsq = sq + d
            if not in_bounds(tsq) or max(abs(file_of(tsq) - file_of(sq)), abs(rank_of(tsq) - rank_of(sq))) != 1:
                continue
            t = self.board[tsq]
            if t is None or color_of(t) != self.side:
                moves.append(Move(sq, tsq, p, t))
        if self.side == WHITE and sq == 4 and not self.king_in_check(WHITE):
            if "K" in self.castling and self.board[5] is None and self.board[6] is None and not self.attacked(5, BLACK) and not self.attacked(6, BLACK):
                moves.append(Move(4, 6, p, None, castle=True))
            if "Q" in self.castling and self.board[1] is None and self.board[2] is None and self.board[3] is None and not self.attacked(3, BLACK) and not self.attacked(2, BLACK):
                moves.append(Move(4, 2, p, None, castle=True))
        if self.side == BLACK and sq == 60 and not self.king_in_check(BLACK):
            if "k" in self.castling and self.board[61] is None and self.board[62] is None and not self.attacked(61, WHITE) and not self.attacked(62, WHITE):
                moves.append(Move(60, 62, p, None, castle=True))
            if "q" in self.castling and self.board[57] is None and self.board[58] is None and self.board[59] is None and not self.attacked(59, WHITE) and not self.attacked(58, WHITE):
                moves.append(Move(60, 58, p, None, castle=True))

    def evaluate(self):
        score = 0
        for sq, p in enumerate(self.board):
            if p is None:
                continue
            val = PIECE_VALUES[piece_type(p)]
            if color_of(p) == WHITE:
                score += val
            else:
                score -= val
            if piece_type(p) == PAWN:
                rank = rank_of(sq) if color_of(p) == WHITE else 7 - rank_of(sq)
                score += (rank * 4) if color_of(p) == WHITE else -(rank * 4)
        return score if self.side == WHITE else -score


class Move:
    __slots__ = ("from_sq", "to_sq", "piece", "captured", "promotion", "ep_capture", "castle")

    def __init__(self, from_sq, to_sq, piece, captured, promotion=None, ep_capture=None, castle=False):
        self.from_sq = from_sq
        self.to_sq = to_sq
        self.piece = piece
        self.captured = captured
        self.promotion = promotion
        self.ep_capture = ep_capture
        self.castle = castle

    def uci(self):
        s = sq_to_str(self.from_sq) + sq_to_str(self.to_sq)
        if self.promotion:
            s += self.promotion.lower()
        return s


def move_score(pos, mv):
    score = 0
    if mv.captured is not None:
        score += 10 * PIECE_VALUES[piece_type(mv.captured)] - PIECE_VALUES[piece_type(mv.piece)]
    if mv.promotion:
        score += PIECE_VALUES[piece_type(mv.promotion)] - PIECE_VALUES[PAWN]
    if mv.castle:
        score += 20
    return score


def search_bestmove(pos, movetime_ms):
    deadline = time.perf_counter() + max(0.005, movetime_ms / 1000.0 - 0.002)
    moves = pos.legal_moves()
    if not moves:
        return "0000"
    moves.sort(key=lambda m: move_score(pos, m), reverse=True)

    best = moves[0]
    best_score = -10**9

    def qsearch(alpha, beta):
        stand = pos.evaluate()
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        caps = [m for m in pos.legal_moves() if m.captured is not None or m.ep_capture is not None or m.promotion is not None]
        caps.sort(key=lambda m: move_score(pos, m), reverse=True)
        for mv in caps:
            if time.perf_counter() > deadline:
                return alpha
            pos.make_move(mv)
            score = -qsearch(-beta, -alpha)
            pos.unmake()
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    def alphabeta(depth, alpha, beta):
        nonlocal best, best_score
        if time.perf_counter() > deadline:
            return pos.evaluate()
        if depth == 0:
            return qsearch(alpha, beta)
        moves = pos.legal_moves()
        if not moves:
            return -100000 if pos.king_in_check(pos.side) else 0
        moves.sort(key=lambda m: move_score(pos, m), reverse=True)
        value = -10**9
        for mv in moves:
            if time.perf_counter() > deadline:
                break
            pos.make_move(mv)
            score = -alphabeta(depth - 1, -beta, -alpha)
            pos.unmake()
            if score > value:
                value = score
            if score > alpha:
                alpha = score
                if depth == root_depth:
                    best = mv
                    best_score = score
            if alpha >= beta:
                break
        return value

    root_depth = 1
    while True:
        if time.perf_counter() > deadline:
            break
        root_depth += 1
        alphabeta(root_depth, -1000000, 1000000)
        if time.perf_counter() > deadline:
            break
    return best.uci()


def main():
    pos = Position()
    pos.set_startpos()
    for raw in sys.stdin:
        cmd = raw.strip().split()
        if not cmd:
            continue
        if cmd[0] == "uci":
            print("id name SimplePythonEngine")
            print("id author OpenAI")
            print("uciok")
            sys.stdout.flush()
        elif cmd[0] == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd[0] == "ucinewgame":
            pos.set_fen("rn1qkbnr/ppp1pppp/8/3p4/3P4/5N2/PPP1PPPP/RNBQKB1R w KQkq - 0 3")
        elif cmd[0] == "position":
            pos.parse_position(cmd)
        elif cmd[0] == "go":
            ms = 20
            if len(cmd) >= 3 and cmd[1] == "movetime":
                try:
                    ms = int(cmd[2])
                except Exception:
                    ms = 20
            bm = search_bestmove(pos, ms)
            print("bestmove", bm)
            sys.stdout.flush()
        elif cmd[0] == "quit":
            break


if __name__ == "__main__":
    main()

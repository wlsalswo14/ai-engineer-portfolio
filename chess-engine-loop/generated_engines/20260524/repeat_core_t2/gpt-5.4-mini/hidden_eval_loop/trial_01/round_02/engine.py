import sys
import time


FILES = "abcdefgh"
RANKS = "12345678"
WHITE, BLACK = 0, 1

PIECE_VALUES = {
    "P": 100,
    "N": 320,
    "B": 330,
    "R": 500,
    "Q": 900,
    "K": 0,
    "p": -100,
    "n": -320,
    "b": -330,
    "r": -500,
    "q": -900,
    "k": 0,
}

KNIGHT_DELTAS = (-17, -15, -10, -6, 6, 10, 15, 17)
BISHOP_DELTAS = (-9, -7, 7, 9)
ROOK_DELTAS = (-8, -1, 1, 8)
KING_DELTAS = (-9, -8, -7, -1, 1, 7, 8, 9)

PROMO_PIECES = ("q", "r", "b", "n")


def is_on_board(sq):
    return 0 <= sq < 64


def file_of(sq):
    return sq & 7


def rank_of(sq):
    return sq >> 3


def square_to_uci(sq):
    return FILES[file_of(sq)] + RANKS[rank_of(sq)]


def uci_to_square(s):
    return (int(s[1]) - 1) * 8 + (ord(s[0]) - 97)


def piece_color(piece):
    return WHITE if piece.isupper() else BLACK


def opposite(color):
    return 1 - color


def piece_type(piece):
    return piece.upper()


class Move:
    __slots__ = ("from_sq", "to_sq", "promo", "flag")

    def __init__(self, from_sq, to_sq, promo=None, flag=0):
        self.from_sq = from_sq
        self.to_sq = to_sq
        self.promo = promo
        self.flag = flag

    def uci(self):
        s = square_to_uci(self.from_sq) + square_to_uci(self.to_sq)
        if self.promo:
            s += self.promo
        return s


class Position:
    __slots__ = ("board", "turn", "castling", "ep", "halfmove", "fullmove", "king_sq")

    def __init__(self):
        self.board = [""] * 64
        self.turn = WHITE
        self.castling = 0
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = [60, 4]

    def clone(self):
        p = Position()
        p.board = self.board[:]
        p.turn = self.turn
        p.castling = self.castling
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        p.king_sq = self.king_sq[:]
        return p

    def set_startpos(self):
        self.set_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            self.set_startpos()
            return
        board_part, turn_part, castling_part, ep_part = parts[:4]
        self.board = [""] * 64
        self.king_sq = [-1, -1]
        ranks = board_part.split("/")
        if len(ranks) != 8:
            self.set_startpos()
            return
        sq = 56
        for row in ranks:
            file_idx = 0
            for ch in row:
                if ch.isdigit():
                    file_idx += int(ch)
                else:
                    idx = sq + file_idx
                    self.board[idx] = ch
                    if ch == "K":
                        self.king_sq[WHITE] = idx
                    elif ch == "k":
                        self.king_sq[BLACK] = idx
                    file_idx += 1
            sq -= 8
        self.turn = WHITE if turn_part == "w" else BLACK
        self.castling = 0
        if "K" in castling_part:
            self.castling |= 1
        if "Q" in castling_part:
            self.castling |= 2
        if "k" in castling_part:
            self.castling |= 4
        if "q" in castling_part:
            self.castling |= 8
        self.ep = -1 if ep_part == "-" else uci_to_square(ep_part)
        self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
        if self.king_sq[WHITE] == -1 or self.king_sq[BLACK] == -1:
            # Fallback to a safe default if the position is malformed.
            self.set_startpos()

    def parse_position(self, tokens):
        if not tokens:
            return
        i = 0
        if tokens[0] == "startpos":
            self.set_startpos()
            i = 1
        elif tokens[0] == "fen":
            fen_fields = []
            i = 1
            while i < len(tokens) and tokens[i] != "moves" and len(fen_fields) < 6:
                fen_fields.append(tokens[i])
                i += 1
            self.set_fen(" ".join(fen_fields))
        else:
            self.set_startpos()
        if i < len(tokens) and tokens[i] == "moves":
            i += 1
            while i < len(tokens):
                self.push_uci(tokens[i])
                i += 1

    def is_square_attacked(self, sq, by_color):
        board = self.board
        # pawns
        if by_color == WHITE:
            for d in (-7, -9):
                t = sq + d
                if is_on_board(t) and abs(file_of(t) - file_of(sq)) == 1 and board[t] == "P":
                    return True
        else:
            for d in (7, 9):
                t = sq + d
                if is_on_board(t) and abs(file_of(t) - file_of(sq)) == 1 and board[t] == "p":
                    return True
        # knights
        attacker = "N" if by_color == WHITE else "n"
        for d in KNIGHT_DELTAS:
            t = sq + d
            if is_on_board(t) and abs(file_of(t) - file_of(sq)) in (1, 2) and board[t] == attacker:
                return True
        # sliders
        for d in BISHOP_DELTAS:
            t = sq + d
            while is_on_board(t) and abs(file_of(t) - file_of(t - d)) == 1:
                p = board[t]
                if p:
                    if piece_color(p) == by_color and p.upper() in ("B", "Q"):
                        return True
                    break
                t += d
        for d in ROOK_DELTAS:
            t = sq + d
            while is_on_board(t):
                if d in (-1, 1) and abs(file_of(t) - file_of(t - d)) != 1:
                    break
                p = board[t]
                if p:
                    if piece_color(p) == by_color and p.upper() in ("R", "Q"):
                        return True
                    break
                t += d
        # king
        attacker = "K" if by_color == WHITE else "k"
        for d in KING_DELTAS:
            t = sq + d
            if is_on_board(t) and max(abs(file_of(t) - file_of(sq)), abs(rank_of(t) - rank_of(sq))) == 1:
                if board[t] == attacker:
                    return True
        return False

    def in_check(self, color):
        ksq = self.king_sq[color]
        if ksq < 0:
            return False
        return self.is_square_attacked(ksq, opposite(color))

    def gen_pseudo_moves(self):
        board = self.board
        color = self.turn
        own_upper = color == WHITE
        for sq, p in enumerate(board):
            if not p or piece_color(p) != color:
                continue
            pt = p.upper()
            if pt == "P":
                direction = 8 if color == WHITE else -8
                start_rank = 1 if color == WHITE else 6
                promo_rank = 6 if color == WHITE else 1
                one = sq + direction
                if is_on_board(one) and not board[one]:
                    if rank_of(sq) == promo_rank:
                        for pr in PROMO_PIECES:
                            yield Move(sq, one, pr)
                    else:
                        yield Move(sq, one)
                        two = sq + 2 * direction
                        if rank_of(sq) == start_rank and is_on_board(two) and not board[two]:
                            yield Move(sq, two)
                for cap_dir in (direction - 1, direction + 1):
                    to = sq + cap_dir
                    if not is_on_board(to):
                        continue
                    if abs(file_of(to) - file_of(sq)) != 1:
                        continue
                    target = board[to]
                    if target and piece_color(target) != color:
                        if rank_of(sq) == promo_rank:
                            for pr in PROMO_PIECES:
                                yield Move(sq, to, pr)
                        else:
                            yield Move(sq, to)
                    elif to == self.ep:
                        yield Move(sq, to, flag=1)
            elif pt == "N":
                for d in KNIGHT_DELTAS:
                    to = sq + d
                    if not is_on_board(to):
                        continue
                    if abs(file_of(to) - file_of(sq)) not in (1, 2):
                        continue
                    target = board[to]
                    if not target or piece_color(target) != color:
                        yield Move(sq, to)
            elif pt in ("B", "R", "Q"):
                deltas = BISHOP_DELTAS if pt == "B" else ROOK_DELTAS if pt == "R" else BISHOP_DELTAS + ROOK_DELTAS
                for d in deltas:
                    to = sq + d
                    while is_on_board(to):
                        if d in (-1, 1) and abs(file_of(to) - file_of(to - d)) != 1:
                            break
                        if d in (-9, 7) and abs(file_of(to) - file_of(to - d)) != 1:
                            break
                        if d in (-7, 9) and abs(file_of(to) - file_of(to - d)) != 1:
                            break
                        target = board[to]
                        if not target:
                            yield Move(sq, to)
                        else:
                            if piece_color(target) != color:
                                yield Move(sq, to)
                            break
                        to += d
            elif pt == "K":
                for d in KING_DELTAS:
                    to = sq + d
                    if not is_on_board(to):
                        continue
                    if max(abs(file_of(to) - file_of(sq)), abs(rank_of(to) - rank_of(sq))) != 1:
                        continue
                    target = board[to]
                    if not target or piece_color(target) != color:
                        yield Move(sq, to)
                if color == WHITE and sq == 60:
                    if self.castling & 1 and not board[61] and not board[62] and board[63] == "R":
                        if not self.is_square_attacked(60, BLACK) and not self.is_square_attacked(61, BLACK) and not self.is_square_attacked(62, BLACK):
                            yield Move(sq, 62, flag=2)
                    if self.castling & 2 and not board[59] and not board[58] and not board[57] and board[56] == "R":
                        if not self.is_square_attacked(60, BLACK) and not self.is_square_attacked(59, BLACK) and not self.is_square_attacked(58, BLACK):
                            yield Move(sq, 58, flag=2)
                elif color == BLACK and sq == 4:
                    if self.castling & 4 and not board[5] and not board[6] and board[7] == "r":
                        if not self.is_square_attacked(4, WHITE) and not self.is_square_attacked(5, WHITE) and not self.is_square_attacked(6, WHITE):
                            yield Move(sq, 6, flag=2)
                    if self.castling & 8 and not board[3] and not board[2] and not board[1] and board[0] == "r":
                        if not self.is_square_attacked(4, WHITE) and not self.is_square_attacked(3, WHITE) and not self.is_square_attacked(2, WHITE):
                            yield Move(sq, 2, flag=2)

    def legal_moves(self):
        moves = []
        for mv in self.gen_pseudo_moves():
            state = self.make_move(mv)
            if state and not self.in_check(opposite(self.turn)):
                moves.append(mv)
            self.unmake_move(mv, state)
        return moves

    def make_move(self, mv):
        board = self.board
        piece = board[mv.from_sq]
        captured = board[mv.to_sq]
        state = (piece, captured, self.castling, self.ep, self.halfmove, self.fullmove, self.king_sq[:])
        board[mv.from_sq] = ""
        self.ep = -1
        self.halfmove += 1
        if piece.upper() == "P":
            self.halfmove = 0
        if captured:
            self.halfmove = 0
        if mv.flag == 1:
            cap_sq = mv.to_sq - (8 if self.turn == WHITE else -8)
            captured = board[cap_sq]
            board[cap_sq] = ""
        if piece.upper() == "K":
            self.halfmove = 0
            if self.turn == WHITE:
                self.castling &= ~3
            else:
                self.castling &= ~12
            self.king_sq[self.turn] = mv.to_sq
            if mv.flag == 2:
                if mv.to_sq == 62:
                    board[63] = ""
                    board[61] = "R"
                elif mv.to_sq == 58:
                    board[56] = ""
                    board[59] = "R"
                elif mv.to_sq == 6:
                    board[7] = ""
                    board[5] = "r"
                elif mv.to_sq == 2:
                    board[0] = ""
                    board[3] = "r"
        if piece.upper() == "R":
            if mv.from_sq == 63:
                self.castling &= ~1
            elif mv.from_sq == 56:
                self.castling &= ~2
            elif mv.from_sq == 7:
                self.castling &= ~4
            elif mv.from_sq == 0:
                self.castling &= ~8
        if captured.upper() == "R" if captured else False:
            if mv.to_sq == 63:
                self.castling &= ~1
            elif mv.to_sq == 56:
                self.castling &= ~2
            elif mv.to_sq == 7:
                self.castling &= ~4
            elif mv.to_sq == 0:
                self.castling &= ~8
        if piece.upper() == "P" and abs(mv.to_sq - mv.from_sq) == 16:
            self.ep = (mv.from_sq + mv.to_sq) // 2
        if mv.promo:
            board[mv.to_sq] = mv.promo.upper() if self.turn == WHITE else mv.promo.lower()
        else:
            board[mv.to_sq] = piece
        if self.turn == BLACK:
            self.fullmove += 1
        self.turn = opposite(self.turn)
        return state

    def unmake_move(self, mv, state):
        if state is None:
            return
        piece, captured, castling, ep, halfmove, fullmove, king_sq = state
        self.turn = opposite(self.turn)
        board = self.board
        board[mv.from_sq] = piece
        if mv.flag == 2:
            if mv.to_sq == 62:
                board[63] = "R"
                board[61] = ""
            elif mv.to_sq == 58:
                board[56] = "R"
                board[59] = ""
            elif mv.to_sq == 6:
                board[7] = "r"
                board[5] = ""
            elif mv.to_sq == 2:
                board[0] = "r"
                board[3] = ""
        if mv.flag == 1:
            cap_sq = mv.to_sq - (8 if self.turn == WHITE else -8)
            board[cap_sq] = "p" if self.turn == WHITE else "P"
            board[mv.to_sq] = ""
        else:
            board[mv.to_sq] = captured
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.fullmove = fullmove
        self.king_sq = king_sq

    def push_uci(self, uci):
        legal = self.legal_moves()
        for mv in legal:
            if mv.uci() == uci:
                self.make_move(mv)
                return True
        # If move is not legal, ignore it to avoid hanging on malformed input.
        return False

    def evaluate(self):
        score = 0
        board = self.board
        for sq, p in enumerate(board):
            if not p:
                continue
            score += PIECE_VALUES[p]
            if p.upper() == "P":
                advance = rank_of(sq) if p.isupper() else 7 - rank_of(sq)
                score += (advance * 6) if p.isupper() else -(advance * 6)
            elif p.upper() in ("N", "B"):
                center = 3 - abs(3.5 - file_of(sq)) - abs(3.5 - rank_of(sq))
                score += int(center * 4) if p.isupper() else int(-center * 4)
        if self.in_check(WHITE):
            score -= 12
        if self.in_check(BLACK):
            score += 12
        return score


def order_moves(pos, moves):
    def key(mv):
        target = pos.board[mv.to_sq]
        score = 0
        if mv.flag == 2:
            score += 10000
        if mv.promo:
            score += 8000 + PIECE_VALUES[mv.promo.upper()]
        if target:
            score += 5000 + abs(PIECE_VALUES[target]) - abs(PIECE_VALUES[pos.board[mv.from_sq]])
        if mv.flag == 1:
            score += 3000
        if pos.board[mv.from_sq].upper() == "P":
            score += 10
        return -score
    return sorted(moves, key=key)


def quiesce(pos, alpha, beta, deadline):
    stand = pos.evaluate()
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    if time.monotonic() >= deadline:
        raise TimeoutError
    moves = []
    for mv in pos.gen_pseudo_moves():
        target = pos.board[mv.to_sq]
        if target or mv.flag == 1 or mv.promo or mv.flag == 2:
            state = pos.make_move(mv)
            if not pos.in_check(opposite(pos.turn)):
                moves.append((mv, state))
            pos.unmake_move(mv, state)
    for mv in order_moves(pos, [m for m, _ in moves]):
        state = pos.make_move(mv)
        if pos.in_check(opposite(pos.turn)):
            pos.unmake_move(mv, state)
            continue
        score = -quiesce(pos, -beta, -alpha, deadline)
        pos.unmake_move(mv, state)
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
    return alpha


def negamax(pos, depth, alpha, beta, deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError
    if depth <= 0:
        return quiesce(pos, alpha, beta, deadline)
    moves = pos.legal_moves()
    if not moves:
        if pos.in_check(pos.turn):
            return -100000 + (4 - depth)
        return 0
    best = -10**9
    for mv in order_moves(pos, moves):
        state = pos.make_move(mv)
        score = -negamax(pos, depth - 1, -beta, -alpha, deadline)
        pos.unmake_move(mv, state)
        if score > best:
            best = score
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
    return best


def search_bestmove(pos, movetime_ms):
    deadline = time.monotonic() + max(0.001, movetime_ms / 1000.0 - 0.002)
    legal = pos.legal_moves()
    if not legal:
        return "0000"
    best = legal[0]
    best_score = -10**9
    depth = 1
    while True:
        if time.monotonic() >= deadline:
            break
        try:
            cur_best = best
            cur_score = -10**9
            for mv in order_moves(pos, legal):
                state = pos.make_move(mv)
                score = -negamax(pos, depth - 1, -10**9, 10**9, deadline)
                pos.unmake_move(mv, state)
                if score > cur_score:
                    cur_score = score
                    cur_best = mv
            if time.monotonic() < deadline:
                best = cur_best
                best_score = cur_score
            depth += 1
        except TimeoutError:
            break
    return best.uci() if best else "0000"


def main():
    pos = Position()
    pos.set_startpos()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        if cmd == "uci":
            sys.stdout.write("id name SimplePythonEngine\n")
            sys.stdout.write("id author codex\n")
            sys.stdout.write("uciok\n")
            sys.stdout.flush()
        elif cmd == "isready":
            sys.stdout.write("readyok\n")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            pos.set_fen("startpos")
        elif cmd == "position":
            pos.parse_position(parts[1:])
        elif cmd == "go":
            movetime = 20
            if "movetime" in parts:
                idx = parts.index("movetime")
                if idx + 1 < len(parts):
                    try:
                        movetime = int(parts[idx + 1])
                    except ValueError:
                        movetime = 20
            best = search_bestmove(pos, movetime)
            sys.stdout.write(f"bestmove {best}\n")
            sys.stdout.flush()
        elif cmd == "quit":
            break


if __name__ == "__main__":
    main()

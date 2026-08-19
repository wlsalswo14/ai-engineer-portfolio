import sys
import time


FILES = "abcdefgh"
RANKS = "12345678"
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


def on_board(sq):
    return 0 <= sq < 64


def file_of(sq):
    return sq & 7


def rank_of(sq):
    return sq >> 3


def square_name(sq):
    return FILES[file_of(sq)] + RANKS[rank_of(sq)]


def square_index(name):
    return (int(name[1]) - 1) * 8 + FILES.index(name[0])


def opponent(color):
    return "b" if color == "w" else "w"


class Move:
    __slots__ = ("from_sq", "to_sq", "promo", "flag")

    def __init__(self, from_sq, to_sq, promo=None, flag=""):
        self.from_sq = from_sq
        self.to_sq = to_sq
        self.promo = promo
        self.flag = flag

    def uci(self):
        s = square_name(self.from_sq) + square_name(self.to_sq)
        return s + (self.promo.lower() if self.promo else "")


class Position:
    def __init__(self):
        self.reset()

    def reset(self):
        self.board = [None] * 64
        self.side = "w"
        self.castling = "KQkq"
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.set_startpos()

    def set_startpos(self):
        self.set_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            self.set_startpos()
            return
        board_part, side, castling, ep = parts[:4]
        self.board = [None] * 64
        sq = 56
        for ch in board_part:
            if ch == "/":
                sq -= 16
            elif ch.isdigit():
                sq += int(ch)
            else:
                self.board[sq] = ch
                sq += 1
        self.side = side if side in ("w", "b") else "w"
        self.castling = "" if castling == "-" else castling
        self.ep = None if ep == "-" else square_index(ep)
        self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

    def clone(self):
        p = Position.__new__(Position)
        p.board = self.board[:]
        p.side = self.side
        p.castling = self.castling
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        return p

    def king_square(self, color):
        target = "K" if color == "w" else "k"
        for i, pc in enumerate(self.board):
            if pc == target:
                return i
        return -1

    def is_square_attacked(self, sq, by_color):
        b = self.board
        f = file_of(sq)
        r = rank_of(sq)
        if by_color == "w":
            for d in (-9, -7):
                s = sq + d
                if on_board(s) and b[s] == "P":
                    if abs(file_of(s) - f) == 1 and rank_of(s) == r - 1:
                        return True
        else:
            for d in (7, 9):
                s = sq + d
                if on_board(s) and b[s] == "p":
                    if abs(file_of(s) - f) == 1 and rank_of(s) == r + 1:
                        return True
        for d in KNIGHT_DELTAS:
            s = sq + d
            if not on_board(s):
                continue
            if abs(file_of(s) - f) > 2:
                continue
            pc = b[s]
            if by_color == "w" and pc == "N":
                return True
            if by_color == "b" and pc == "n":
                return True
        for d in BISHOP_DELTAS:
            s = sq + d
            while on_board(s) and abs(file_of(s) - file_of(s - d)) == 1:
                pc = b[s]
                if pc:
                    if by_color == "w" and pc in ("B", "Q"):
                        return True
                    if by_color == "b" and pc in ("b", "q"):
                        return True
                    break
                s += d
        for d in ROOK_DELTAS:
            s = sq + d
            while on_board(s) and (d in (-1, 1) and rank_of(s) == r or d in (-8, 8)):
                if d in (-1, 1) and abs(file_of(s) - file_of(s - d)) != 1:
                    break
                pc = b[s]
                if pc:
                    if by_color == "w" and pc in ("R", "Q"):
                        return True
                    if by_color == "b" and pc in ("r", "q"):
                        return True
                    break
                s += d
        for d in KING_DELTAS:
            s = sq + d
            if not on_board(s) or abs(file_of(s) - f) > 1:
                continue
            pc = b[s]
            if by_color == "w" and pc == "K":
                return True
            if by_color == "b" and pc == "k":
                return True
        return False

    def in_check(self, color=None):
        color = color or self.side
        ks = self.king_square(color)
        return ks != -1 and self.is_square_attacked(ks, opponent(color))

    def generate_pseudo(self):
        b = self.board
        side = self.side
        moves = []
        for sq, pc in enumerate(b):
            if not pc:
                continue
            if side == "w" and not pc.isupper():
                continue
            if side == "b" and not pc.islower():
                continue
            color = "w" if pc.isupper() else "b"
            if pc in ("P", "p"):
                direction = 8 if pc == "P" else -8
                start_rank = 1 if pc == "P" else 6
                promo_rank = 6 if pc == "P" else 1
                one = sq + direction
                if on_board(one) and b[one] is None:
                    if rank_of(sq) == promo_rank:
                        for pr in "QRBN":
                            moves.append(Move(sq, one, pr if pc == "P" else pr.lower()))
                    else:
                        moves.append(Move(sq, one))
                    two = sq + direction * 2
                    if rank_of(sq) == start_rank and on_board(two) and b[two] is None:
                        moves.append(Move(sq, two))
                for cap_dir in (direction - 1, direction + 1):
                    to = sq + cap_dir
                    if not on_board(to) or abs(file_of(to) - file_of(sq)) != 1:
                        continue
                    target = b[to]
                    if target and target.isupper() != pc.isupper():
                        if rank_of(sq) == promo_rank:
                            for pr in "QRBN":
                                moves.append(Move(sq, to, pr if pc == "P" else pr.lower()))
                        else:
                            moves.append(Move(sq, to))
                    if self.ep is not None and to == self.ep:
                        moves.append(Move(sq, to, flag="ep"))
            elif pc.upper() == "N":
                for d in KNIGHT_DELTAS:
                    to = sq + d
                    if not on_board(to) or abs(file_of(to) - file_of(sq)) > 2:
                        continue
                    target = b[to]
                    if not target or target.isupper() != pc.isupper():
                        moves.append(Move(sq, to))
            elif pc.upper() in ("B", "R", "Q"):
                deltas = BISHOP_DELTAS if pc.upper() == "B" else ROOK_DELTAS if pc.upper() == "R" else BISHOP_DELTAS + ROOK_DELTAS
                for d in deltas:
                    to = sq + d
                    while on_board(to) and abs(file_of(to) - file_of(to - d)) <= 1:
                        if d in (-1, 1) and rank_of(to) != rank_of(to - d):
                            break
                        target = b[to]
                        if target:
                            if target.isupper() != pc.isupper():
                                moves.append(Move(sq, to))
                            break
                        moves.append(Move(sq, to))
                        to += d
            elif pc.upper() == "K":
                for d in KING_DELTAS:
                    to = sq + d
                    if not on_board(to) or abs(file_of(to) - file_of(sq)) > 1:
                        continue
                    target = b[to]
                    if not target or target.isupper() != pc.isupper():
                        moves.append(Move(sq, to))
                if side == "w" and sq == 4 and not self.in_check("w"):
                    if "K" in self.castling and b[5] is None and b[6] is None and b[7] == "R":
                        if not self.is_square_attacked(5, "b") and not self.is_square_attacked(6, "b"):
                            moves.append(Move(4, 6, flag="castle"))
                    if "Q" in self.castling and b[1] is None and b[2] is None and b[3] is None and b[0] == "R":
                        if not self.is_square_attacked(3, "b") and not self.is_square_attacked(2, "b"):
                            moves.append(Move(4, 2, flag="castle"))
                if side == "b" and sq == 60 and not self.in_check("b"):
                    if "k" in self.castling and b[61] is None and b[62] is None and b[63] == "r":
                        if not self.is_square_attacked(61, "w") and not self.is_square_attacked(62, "w"):
                            moves.append(Move(60, 62, flag="castle"))
                    if "q" in self.castling and b[57] is None and b[58] is None and b[59] is None and b[56] == "r":
                        if not self.is_square_attacked(59, "w") and not self.is_square_attacked(58, "w"):
                            moves.append(Move(60, 58, flag="castle"))
        return moves

    def legal_moves(self):
        res = []
        for mv in self.generate_pseudo():
            nxt = self.make_move(mv)
            if not nxt.in_check(opponent(nxt.side)):
                res.append(mv)
        return res

    def make_move(self, mv):
        n = self.clone()
        b = n.board
        piece = b[mv.from_sq]
        captured = b[mv.to_sq]
        b[mv.from_sq] = None
        n.ep = None
        if mv.flag == "castle":
            b[mv.to_sq] = piece
            if mv.to_sq == 6:
                b[5] = b[7]
                b[7] = None
            elif mv.to_sq == 2:
                b[3] = b[0]
                b[0] = None
            elif mv.to_sq == 62:
                b[61] = b[63]
                b[63] = None
            elif mv.to_sq == 58:
                b[59] = b[56]
                b[56] = None
        elif mv.flag == "ep":
            b[mv.to_sq] = piece
            cap = mv.to_sq - 8 if piece == "P" else mv.to_sq + 8
            b[cap] = None
        else:
            b[mv.to_sq] = piece if mv.promo is None else mv.promo
        if piece in ("P", "p") or captured:
            n.halfmove = 0
        else:
            n.halfmove += 1
        if piece == "P" and mv.to_sq - mv.from_sq == 16:
            n.ep = mv.from_sq + 8
        elif piece == "p" and mv.from_sq - mv.to_sq == 16:
            n.ep = mv.from_sq - 8
        if piece == "K":
            n.castling = n.castling.replace("K", "").replace("Q", "")
        elif piece == "k":
            n.castling = n.castling.replace("k", "").replace("q", "")
        elif mv.from_sq == 0 or mv.to_sq == 0:
            n.castling = n.castling.replace("Q", "")
        elif mv.from_sq == 7 or mv.to_sq == 7:
            n.castling = n.castling.replace("K", "")
        elif mv.from_sq == 56 or mv.to_sq == 56:
            n.castling = n.castling.replace("q", "")
        elif mv.from_sq == 63 or mv.to_sq == 63:
            n.castling = n.castling.replace("k", "")
        n.side = opponent(self.side)
        if n.side == "w":
            n.fullmove += 1
        return n

    def evaluate(self):
        score = 0
        for sq, pc in enumerate(self.board):
            if not pc:
                continue
            val = PIECE_VALUES[pc.upper()]
            bonus = 0
            r = rank_of(sq)
            if pc == "P":
                bonus = r * 10
            elif pc == "p":
                bonus = (7 - r) * 10
            if pc.isupper():
                score += val + bonus
            else:
                score -= val + bonus
        if self.in_check("w"):
            score -= 15
        if self.in_check("b"):
            score += 15
        return score if self.side == "w" else -score


class Engine:
    def __init__(self):
        self.pos = Position()

    def parse_position(self, line):
        parts = line.split()
        idx = 1
        if idx >= len(parts):
            return
        if parts[idx] == "startpos":
            self.pos.set_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
            idx += 1
        elif parts[idx] == "fen":
            fen = " ".join(parts[idx + 1:idx + 7]) if len(parts) >= idx + 7 else ""
            self.pos.set_fen(fen)
            idx += 7
        if idx < len(parts) and parts[idx] == "moves":
            for m in parts[idx + 1:]:
                mv = self.find_move(m)
                if mv:
                    self.pos = self.pos.make_move(mv)

    def find_move(self, uci):
        for mv in self.pos.legal_moves():
            if mv.uci() == uci:
                return mv
        return None

    def ordered_moves(self, pos):
        moves = pos.legal_moves()
        scored = []
        for mv in moves:
            score = 0
            target = pos.board[mv.to_sq]
            piece = pos.board[mv.from_sq]
            if mv.flag == "ep":
                score += 105
            if mv.flag == "castle":
                score += 50
            if target:
                score += 10 * PIECE_VALUES[target.upper()] - PIECE_VALUES[piece.upper()]
            if mv.promo:
                score += PIECE_VALUES[mv.promo.upper()]
            scored.append((score, mv))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [mv for _, mv in scored]

    def search(self, pos, depth, alpha, beta, end_time):
        if time.time() >= end_time:
            raise TimeoutError
        moves = self.ordered_moves(pos)
        if depth == 0 or not moves:
            if not moves:
                return (-100000 + (3 - depth)) if pos.in_check(pos.side) else 0, None
            return pos.evaluate(), None
        best = None
        if pos.side == "w":
            value = -10**9
            for mv in moves:
                child = pos.make_move(mv)
                sc, _ = self.search(child, depth - 1, alpha, beta, end_time)
                if sc > value:
                    value, best = sc, mv
                alpha = max(alpha, value)
                if alpha >= beta:
                    break
            return value, best
        else:
            value = 10**9
            for mv in moves:
                child = pos.make_move(mv)
                sc, _ = self.search(child, depth - 1, alpha, beta, end_time)
                if sc < value:
                    value, best = sc, mv
                beta = min(beta, value)
                if alpha >= beta:
                    break
            return value, best

    def bestmove(self, movetime_ms):
        end_time = time.time() + max(0.001, movetime_ms / 1000.0 * 0.95)
        legal = self.pos.legal_moves()
        if not legal:
            return "0000"
        best = legal[0]
        try:
            for depth in range(1, 5):
                _, mv = self.search(self.pos, depth, -10**9, 10**9, end_time)
                if mv is not None:
                    best = mv
        except TimeoutError:
            pass
        return best.uci()


def main():
    eng = Engine()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line == "uci":
            print("id name SimplePythonEngine")
            print("id author openai")
            print("uciok")
        elif line == "isready":
            print("readyok")
        elif line == "ucinewgame":
            eng.pos = Position()
        elif line.startswith("position "):
            eng.parse_position(line)
        elif line.startswith("go "):
            parts = line.split()
            ms = 20
            if "movetime" in parts:
                i = parts.index("movetime")
                if i + 1 < len(parts):
                    try:
                        ms = int(parts[i + 1])
                    except ValueError:
                        pass
            print("bestmove", eng.bestmove(ms))
        elif line == "quit":
            break
        sys.stdout.flush()


if __name__ == "__main__":
    main()

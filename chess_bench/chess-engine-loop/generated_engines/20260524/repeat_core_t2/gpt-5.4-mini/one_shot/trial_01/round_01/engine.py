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

KNIGHT_DELTAS = (-17, -15, -10, -6, 6, 10, 15, 17)
BISHOP_DELTAS = (-9, -7, 7, 9)
ROOK_DELTAS = (-8, -1, 1, 8)
KING_DELTAS = (-9, -8, -7, -1, 1, 7, 8, 9)

PIECE_VALUES = {
    PAWN: 100,
    KNIGHT: 320,
    BISHOP: 330,
    ROOK: 500,
    QUEEN: 900,
    KING: 0,
}

MATE = 100000
INF = 10**9


def sq(file_, rank):
    return rank * 8 + file_


def on_board(index):
    return 0 <= index < 64


def file_of(index):
    return index & 7


def rank_of(index):
    return index >> 3


def color_of(piece):
    return WHITE if piece > 0 else BLACK


def piece_type(piece):
    return abs(piece)


def opposite(color):
    return BLACK if color == WHITE else WHITE


def move_to_uci(move):
    fr, to, promo = move
    s = FILES[file_of(fr)] + RANKS[rank_of(fr)] + FILES[file_of(to)] + RANKS[rank_of(to)]
    if promo:
        s += "nbrq"[promo - 2]
    return s


def uci_to_move(board, token):
    if len(token) < 4:
        return None
    f1 = FILES.find(token[0])
    r1 = RANKS.find(token[1])
    f2 = FILES.find(token[2])
    r2 = RANKS.find(token[3])
    if min(f1, r1, f2, r2) < 0:
        return None
    fr = sq(f1, r1)
    to = sq(f2, r2)
    promo = 0
    if len(token) >= 5:
        promo_map = {"n": KNIGHT, "b": BISHOP, "r": ROOK, "q": QUEEN}
        promo = promo_map.get(token[4], 0)
    for mv in generate_legal_moves(board):
        if mv[0] == fr and mv[1] == to and mv[2] == promo:
            return mv
    return None


class Position:
    def __init__(self):
        self.board = [0] * 64
        self.side = WHITE
        self.castling = set("KQkq")
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = {WHITE: 4, BLACK: 60}

    def clone(self):
        p = Position()
        p.board = self.board[:]
        p.side = self.side
        p.castling = set(self.castling)
        p.ep = self.ep
        p.halfmove = self.halfmove
        p.fullmove = self.fullmove
        p.king_sq = self.king_sq.copy()
        return p


def parse_fen(fen):
    parts = fen.split()
    pos = Position()
    rows = parts[0].split("/")
    for r, row in enumerate(rows):
        file_ = 0
        rank = 7 - r
        for ch in row:
            if ch.isdigit():
                file_ += int(ch)
            else:
                color = WHITE if ch.isupper() else BLACK
                kind = {
                    "p": PAWN, "n": KNIGHT, "b": BISHOP,
                    "r": ROOK, "q": QUEEN, "k": KING
                }[ch.lower()]
                idx = sq(file_, rank)
                pos.board[idx] = kind if color == WHITE else -kind
                if kind == KING:
                    pos.king_sq[color] = idx
                file_ += 1
    pos.side = WHITE if parts[1] == "w" else BLACK
    pos.castling = set([] if parts[2] == "-" else parts[2])
    pos.ep = None if parts[3] == "-" else sq(FILES.index(parts[3][0]), RANKS.index(parts[3][1]))
    pos.halfmove = int(parts[4])
    pos.fullmove = int(parts[5])
    return pos


def startpos():
    return parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


def attacks_square(board, attacker_color, target):
    tf = file_of(target)
    tr = rank_of(target)

    pawn_dirs = (-7, -9) if attacker_color == WHITE else (7, 9)
    for d in pawn_dirs:
        s = target + d
        if on_board(s) and abs(file_of(s) - tf) == 1:
            p = board[s]
            if p and color_of(p) == attacker_color and piece_type(p) == PAWN:
                return True

    for d in KNIGHT_DELTAS:
        s = target + d
        if on_board(s) and max(abs(file_of(s) - tf), abs(rank_of(s) - tr)) == 2:
            p = board[s]
            if p and color_of(p) == attacker_color and piece_type(p) == KNIGHT:
                return True

    for d in BISHOP_DELTAS:
        s = target + d
        while on_board(s) and abs(file_of(s) - file_of(s - d)) == 1:
            p = board[s]
            if p:
                if color_of(p) == attacker_color and (piece_type(p) == BISHOP or piece_type(p) == QUEEN):
                    return True
                break
            s += d

    for d in ROOK_DELTAS:
        s = target + d
        while on_board(s) and ((d in (-1, 1) and rank_of(s) == tr) or d in (-8, 8)):
            p = board[s]
            if p:
                if color_of(p) == attacker_color and (piece_type(p) == ROOK or piece_type(p) == QUEEN):
                    return True
                break
            s += d

    for d in KING_DELTAS:
        s = target + d
        if on_board(s) and max(abs(file_of(s) - tf), abs(rank_of(s) - tr)) == 1:
            p = board[s]
            if p and color_of(p) == attacker_color and piece_type(p) == KING:
                return True
    return False


def in_check(pos, color):
    return attacks_square(pos.board, opposite(color), pos.king_sq[color])


def make_move(pos, move):
    fr, to, promo = move
    piece = pos.board[fr]
    captured = pos.board[to]
    new = pos.clone()
    new.board[fr] = 0
    new.ep = None
    new.halfmove += 1
    if piece_type(piece) == PAWN or captured:
        new.halfmove = 0
    if piece_type(piece) == KING:
        new.king_sq[color_of(piece)] = to
        if color_of(piece) == WHITE:
            new.castling.discard("K")
            new.castling.discard("Q")
        else:
            new.castling.discard("k")
            new.castling.discard("q")
        if fr == 4 and to == 6:
            new.board[7] = 0
            new.board[5] = ROOK
        elif fr == 4 and to == 2:
            new.board[0] = 0
            new.board[3] = ROOK
        elif fr == 60 and to == 62:
            new.board[63] = 0
            new.board[61] = -ROOK
        elif fr == 60 and to == 58:
            new.board[56] = 0
            new.board[59] = -ROOK
    if piece_type(piece) == ROOK:
        if fr == 0: new.castling.discard("Q")
        elif fr == 7: new.castling.discard("K")
        elif fr == 56: new.castling.discard("q")
        elif fr == 63: new.castling.discard("k")
    if captured and piece_type(captured) == ROOK:
        if to == 0: new.castling.discard("Q")
        elif to == 7: new.castling.discard("K")
        elif to == 56: new.castling.discard("q")
        elif to == 63: new.castling.discard("k")
    if piece_type(piece) == PAWN and to == pos.ep and captured == 0 and file_of(fr) != file_of(to):
        cap_sq = to - 8 if color_of(piece) == WHITE else to + 8
        captured = new.board[cap_sq]
        new.board[cap_sq] = 0
        new.halfmove = 0
    if piece_type(piece) == PAWN and abs(to - fr) == 16:
        new.ep = fr + (8 if color_of(piece) == WHITE else -8)
    if promo:
        new.board[to] = promo if color_of(piece) == WHITE else -promo
    else:
        new.board[to] = piece
    if color_of(piece) == BLACK:
        new.fullmove += 1
    new.side = opposite(pos.side)
    return new


def add_move(moves, pos, fr, to, promo=0):
    moves.append((fr, to, promo))


def generate_pseudo_moves(pos):
    moves = []
    side = pos.side
    board = pos.board
    for sqi, piece in enumerate(board):
        if not piece or color_of(piece) != side:
            continue
        kind = piece_type(piece)
        r = rank_of(sqi)
        f = file_of(sqi)
        if kind == PAWN:
            step = 8 if side == WHITE else -8
            one = sqi + step
            start_rank = 1 if side == WHITE else 6
            promo_rank = 6 if side == WHITE else 1
            if on_board(one) and board[one] == 0:
                if r == promo_rank:
                    for pr in (KNIGHT, BISHOP, ROOK, QUEEN):
                        add_move(moves, pos, sqi, one, pr)
                else:
                    add_move(moves, pos, sqi, one)
                    two = sqi + step * 2
                    if r == start_rank and board[two] == 0:
                        add_move(moves, pos, sqi, two)
            for df in (-1, 1):
                tf = f + df
                if 0 <= tf < 8:
                    cap = sqi + step + df
                    if on_board(cap):
                        if board[cap] and color_of(board[cap]) != side:
                            if r == promo_rank:
                                for pr in (KNIGHT, BISHOP, ROOK, QUEEN):
                                    add_move(moves, pos, sqi, cap, pr)
                            else:
                                add_move(moves, pos, sqi, cap)
                        if pos.ep == cap:
                            add_move(moves, pos, sqi, cap)
        elif kind == KNIGHT:
            for d in KNIGHT_DELTAS:
                to = sqi + d
                if on_board(to) and max(abs(file_of(to) - f), abs(rank_of(to) - r)) == 2:
                    if not board[to] or color_of(board[to]) != side:
                        add_move(moves, pos, sqi, to)
        elif kind in (BISHOP, ROOK, QUEEN):
            dirs = []
            if kind in (BISHOP, QUEEN):
                dirs.extend(BISHOP_DELTAS)
            if kind in (ROOK, QUEEN):
                dirs.extend(ROOK_DELTAS)
            for d in dirs:
                to = sqi + d
                while on_board(to) and abs(file_of(to) - file_of(to - d)) <= 1:
                    if board[to]:
                        if color_of(board[to]) != side:
                            add_move(moves, pos, sqi, to)
                        break
                    add_move(moves, pos, sqi, to)
                    if d in (-1, 1) and rank_of(to) != r:
                        break
                    to += d
        elif kind == KING:
            for d in KING_DELTAS:
                to = sqi + d
                if on_board(to) and max(abs(file_of(to) - f), abs(rank_of(to) - r)) == 1:
                    if not board[to] or color_of(board[to]) != side:
                        add_move(moves, pos, sqi, to)
            if side == WHITE and sqi == 4:
                if "K" in pos.castling and board[5] == board[6] == 0 and not in_check(pos, WHITE) and not attacks_square(board, BLACK, 5) and not attacks_square(board, BLACK, 6):
                    add_move(moves, pos, 4, 6)
                if "Q" in pos.castling and board[1] == board[2] == board[3] == 0 and not in_check(pos, WHITE) and not attacks_square(board, BLACK, 3) and not attacks_square(board, BLACK, 2):
                    add_move(moves, pos, 4, 2)
            if side == BLACK and sqi == 60:
                if "k" in pos.castling and board[61] == board[62] == 0 and not in_check(pos, BLACK) and not attacks_square(board, WHITE, 61) and not attacks_square(board, WHITE, 62):
                    add_move(moves, pos, 60, 62)
                if "q" in pos.castling and board[57] == board[58] == board[59] == 0 and not in_check(pos, BLACK) and not attacks_square(board, WHITE, 59) and not attacks_square(board, WHITE, 58):
                    add_move(moves, pos, 60, 58)
    return moves


def generate_legal_moves(pos):
    legal = []
    for mv in generate_pseudo_moves(pos):
        nxt = make_move(pos, mv)
        if not in_check(nxt, opposite(nxt.side)):
            legal.append(mv)
    return legal


def evaluate(pos):
    score = 0
    for i, p in enumerate(pos.board):
        if not p:
            continue
        v = PIECE_VALUES[piece_type(p)]
        if piece_type(p) == PAWN:
            rank_bonus = rank_of(i) if color_of(p) == WHITE else 7 - rank_of(i)
            v += rank_bonus * 4
        if color_of(p) == WHITE:
            score += v
        else:
            score -= v
    if in_check(pos, pos.side):
        score += -15 if pos.side == WHITE else 15
    return score


class SearchTimeout(Exception):
    pass


def ordered_moves(pos, moves):
    scored = []
    for mv in moves:
        fr, to, promo = mv
        capture = pos.board[to]
        score = 0
        if capture:
            score += 10 * PIECE_VALUES[piece_type(capture)] - PIECE_VALUES[piece_type(pos.board[fr])]
        if promo:
            score += PIECE_VALUES[promo] + 800
        if piece_type(pos.board[fr]) == PAWN and abs(to - fr) == 16:
            score += 20
        if piece_type(pos.board[fr]) == KING and abs(to - fr) == 2:
            score += 50
        scored.append((score, mv))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [mv for _, mv in scored]


def negamax(pos, depth, alpha, beta, start, limit):
    if time.time() >= limit:
        raise SearchTimeout
    moves = generate_legal_moves(pos)
    if depth == 0 or not moves:
        if not moves:
            if in_check(pos, pos.side):
                return -MATE + (5 - depth)
            return 0
        return evaluate(pos) if pos.side == WHITE else -evaluate(pos)
    best = -INF
    for mv in ordered_moves(pos, moves):
        child = make_move(pos, mv)
        score = -negamax(child, depth - 1, -beta, -alpha, start, limit)
        if score > best:
            best = score
        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
        if time.time() >= limit:
            raise SearchTimeout
    return best


def search_best_move(pos, movetime_ms):
    legal = generate_legal_moves(pos)
    if not legal:
        return None
    if len(legal) == 1:
        return legal[0]
    limit = time.time() + max(0.01, movetime_ms / 1000.0 * 0.95)
    best = legal[0]
    best_score = -INF
    depth = 1
    while True:
        try:
            cur_best = best
            cur_score = -INF
            for mv in ordered_moves(pos, legal):
                child = make_move(pos, mv)
                score = -negamax(child, depth - 1, -INF, INF, time.time(), limit)
                if score > cur_score:
                    cur_score = score
                    cur_best = mv
                if time.time() >= limit:
                    raise SearchTimeout
            best = cur_best
            best_score = cur_score
            depth += 1
        except SearchTimeout:
            break
        except RecursionError:
            break
    return best


def apply_moves(pos, moves):
    for token in moves:
        mv = uci_to_move(pos, token)
        if mv is None:
            continue
        pos = make_move(pos, mv)
    return pos


def set_position(tokens, current):
    if tokens[0] == "startpos":
        pos = startpos()
        idx = 1
    else:
        fen = []
        idx = 1
        while idx < len(tokens) and tokens[idx] != "moves":
            fen.append(tokens[idx])
            idx += 1
        pos = parse_fen(" ".join(fen))
    if idx < len(tokens) and tokens[idx] == "moves":
        pos = apply_moves(pos, tokens[idx + 1 :])
    return pos


def main():
    pos = startpos()
    for line in sys.stdin:
        cmd = line.strip().split()
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
            pos = startpos()
        elif cmd[0] == "position":
            pos = set_position(cmd[1:], pos)
        elif cmd[0] == "go":
            movetime = 20
            if "movetime" in cmd:
                i = cmd.index("movetime")
                if i + 1 < len(cmd):
                    try:
                        movetime = int(cmd[i + 1])
                    except ValueError:
                        pass
            move = search_best_move(pos, movetime)
            if move is None:
                legal = generate_legal_moves(pos)
                move = legal[0] if legal else None
            print("bestmove " + (move_to_uci(move) if move else "0000"))
            sys.stdout.flush()
        elif cmd[0] == "quit":
            break


if __name__ == "__main__":
    main()

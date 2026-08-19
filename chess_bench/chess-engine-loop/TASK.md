# Task: build a chess engine from scratch

Create a Python file named `engine.py`.

The engine must speak enough UCI over stdin/stdout to play games:

```text
uci                  -> print id/name lines, then uciok
isready              -> print readyok
ucinewgame           -> reset internal state
position startpos [moves ...]
position fen <six-field-fen> [moves ...]
go movetime <ms>     -> print exactly one legal `bestmove <uci_move>`
quit                 -> exit
```

The evaluator will play the engine against Stockfish at a tiny per-move budget.
Stockfish is only the opponent/evaluator. Do not inspect, cite, copy, or adapt
from Stockfish, commercial chess engines, python-chess, Sunfish, TSCP, or any
other chess engine/library source. Implement move generation, position state,
search, and evaluation yourself using only the Python standard library.

Your engine should prioritize:

- always returning legal moves before the timeout,
- not hanging on malformed or unfamiliar positions,
- basic material/king-safety/pawn/piece evaluation,
- at least shallow minimax/alpha-beta or a similarly concrete search,
- fast move ordering so `go movetime 20` still responds.

Leave only `engine.py` as the final engine artifact.

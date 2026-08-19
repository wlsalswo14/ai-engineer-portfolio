# Task: Write A Fog-of-War Chess Move Agent

Write `agent.py` using only the Python standard library.

The evaluator sends one JSON observation per line on stdin. For each observation,
print one move on stdout and flush it.

```python
import json
import sys

for line in sys.stdin:
    observation = json.loads(line)
    print("e2e4", flush=True)
```

The move format is UCI coordinate text such as `e2e4`, `e7e8q`, or `e2e8`.

You are playing a Fog-of-War chess variant:

- the arbiter owns the canonical board;
- you only receive `visible_board`;
- unknown squares are `?`;
- visible empty squares are `.`;
- pieces use normal chess letters, uppercase for white and lowercase for black;
- own pieces are visible;
- a square is visible when one of your pieces could pseudo-legally move there;
- self-check is ignored;
- checkmate and stalemate are disabled;
- the game ends when a king is captured.

The public runner intentionally does not send a hidden-dependent legal-move
list. Submit attempted moves and let the arbiter resolve legality privately.

Restrictions:

- Use Python standard library only.
- Do not import or invoke Stockfish, StockfishFogOfWar, chess libraries,
  subprocesses, local files, network resources, or benchmark source paths.
- Do not try to infer hidden board state from fixture names, local paths, or
  evaluator implementation details.
- Do not hardcode public case ids.

Good general strategies reason from visible pieces only, prioritize immediate
visible king captures, then visible material captures, and otherwise choose
legal-looking developing moves under uncertainty.

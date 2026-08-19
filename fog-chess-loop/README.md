# Fog Chess Loop

This benchmark scores a Fog-of-War Chess move agent under a strict
partial-observation boundary.

The candidate receives only a side-specific observation:

- `visible_board`, with hidden squares as `?`;
- side and turn metadata;
- fogged history;
- previous illegal-attempt feedback when a runner supplies it.

The candidate does not receive the canonical board, a full FEN, or a
hidden-dependent legal-move list. The evaluator privately resolves attempted UCI
moves.

The benchmark is based on the same design pattern as the local FoW chess
prototype: the arbiter owns the full board, visible squares are own pieces plus
pseudo-legal destinations, opponent history is redacted, and illegal moves are
retried or scored without exposing hidden state.

`public_fixtures()` is the small checked-in smoke panel. `generate_fixture_suite()`
adds deterministic seed-based positions for private loop comparisons, including
both white and black move cases.

## Run

```bash
bash benchmarks/data/fog-chess-loop/reproduce.sh smoke
bash benchmarks/data/fog-chess-loop/reproduce.sh eval-included
bash benchmarks/data/fog-chess-loop/reproduce.sh compare
```

Evaluate a candidate:

```bash
python3 benchmarks/runners/fog_chess_loop.py eval \
  --candidate path/to/agent.py \
  --out tmp/fog_chess_candidate.json
```

Compare optional local references:

```bash
STOCKFISH_PATH=/path/to/stockfish \
STOCKFISH_FOG_AGENT=/path/to/stockfish_fog_agent.py \
HTML_FOG_AGENT=/path/to/html_fog_agent \
bash benchmarks/data/fog-chess-loop/reproduce.sh compare
```

Run the asymmetric full-information Stockfish stress panel:

```bash
STOCKFISH_PATH=/path/to/stockfish \
FOG_CHESS_STRESS_AGENT=/path/to/observation_only_agent.py \
FOG_CHESS_STOCKFISH_MOVETIME_MS=20 \
FOG_CHESS_STRESS_MAX_PLIES=40 \
bash benchmarks/data/fog-chess-loop/reproduce.sh stress
```

Plain Stockfish is reported as `stockfish_full_info_reference`: it receives a
full FEN and is therefore a calibration/reference row, not a legal FoW
candidate. King-capture variant positions that plain Stockfish cannot represent
are marked `unsupported_king_capture_variant`. `STOCKFISH_FOG_AGENT` is reported as
`stockfish_fog_observation_agent`: it receives only the same JSONL observations
as candidates. Use this path for a StockfishFogOfWar wrapper that makes decisions
from partial observations.

## Reference Policy

`full_info_reference` is an evaluator-side cheating upper bound. It is useful for
calibration but must not be used as a candidate prompt surface.

A local StockfishFogOfWar wrapper can be evaluated as a normal candidate only if
it consumes the same observation-only JSON protocol. Plain Stockfish should be
treated as a full-information reference unless it is wrapped behind an
observation-pure adapter.

`HTML_FOG_AGENT` is a separate optional observation-only slot for a local
HTML-backed FoW prototype wrapper. It is evaluated through the same JSONL
observation protocol and is reported as `html_fog_observation_agent`; the runner
does not pass full board state, FEN, hidden legal moves, or private markers.

## Full-Info Stockfish Stress

`stress` reports `fow_vs_full_info_stockfish`. This is intentionally not a fair
FoW Elo match. The runner owns the true board, gives the FoW agent only the same
JSONL observation protocol used by candidates, and gives Stockfish the true FEN
on Stockfish turns. Move legality is still resolved by the runner's true board.

Use this mode as an anti-saturation stress anchor: Stockfish can exploit hidden
state, so the useful comparison is how different observation-only agents survive
under the same full-information adversary. The output records survival plies,
candidate illegal/timeout/leak counts, Stockfish illegal/timeout counts, material
loss, and per-ply moves. A candidate row with hidden-board, full-FEN, legal-move,
or private-marker leakage is invalidated.

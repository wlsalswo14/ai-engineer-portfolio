# Chess Engine Loop Benchmark

This benchmark asks an LLM to create a Python UCI chess engine from scratch and
scores the generated `engine.py` against Stockfish. It was added as a curated
benchmark package: runner code lives in `benchmarks/runners/`, while all
benchmark-specific task text, suites, generated engines, and results live under
this folder.

## Layout Decision

Use one folder per benchmark under `benchmarks/data/`, and keep executable
runners in `benchmarks/runners/`.

That preserves the existing Loopsy convention:

- shared or reusable scoring code: `benchmarks/runners/`
- benchmark-specific task/data/results: `benchmarks/data/<benchmark-id>/`

For this benchmark the ID is `chess-engine-loop`.

## Contents

- `TASK.md`: exact candidate task prompt.
- `suites.json`: public description of the two evaluation suites.
- `requirements.txt`: Python dependency used by the runner.
- `reproduce.sh`: convenience wrapper for smoke checks and included-candidate evaluation.
- `results_20260524.md`: human-readable result report.
- `results/20260524/summary.json`: compact machine-readable summary.
- `results/20260524/source_reports/*.json`: sanitized per-run report JSON.
- `generated_engines/20260524/`: generated candidate `engine.py` files and manifest.

Raw Codex event streams, private memory, local temp directories, and personal
machine paths are intentionally excluded.

## Benchmark Contract

Candidate artifact:

```text
engine.py
```

Candidate constraints:

- Python standard library only.
- Implement enough UCI to answer `uci`, `isready`, `ucinewgame`,
  `position ...`, `go movetime <ms>`, and `quit`.
- Do not inspect, cite, copy, or adapt Stockfish, commercial chess engines,
  python-chess, Sunfish, TSCP, or other chess engine/library source.
- Static checks reject Stockfish mentions, `import chess`, python-chess
  mentions, and known engine-source markers.

Stockfish is used only as evaluator/opponent.

## Result Snapshot

Settings:

- Models: `gpt-5.4-mini low`, `gpt-5.5 low`
- Suites: `opening_gauntlet`, `advantage_conversion`
- Games per result row: `16`
- Candidate time: `go movetime 20`
- Stockfish: `UCI_Elo=1320`, depth `1`
- Max plies: `40`
- Elo estimate: Jeffreys-smoothed W/D/L against reference Elo 1320

Mean best Elo by model and loop structure:

| Model | one_shot | hidden_eval_loop | cumulative_hidden_eval_loop | solver_visible_public_eval |
|---|---:|---:|---:|---:|
| `gpt-5.4-mini` | 926.5 | 945.0 | 1115.0 | 899.0 |
| `gpt-5.5` | 1069.0 | 1027.5 | 1129.0 | 942.0 |

Main conclusion: cumulative previous-code feedback was the best coarse
structure for both models, but additional rounds were not monotonic. Bigger
model plus same loop was usually stronger, but timeout/completion risk and
round-to-round regressions remained.

## Reproduce

Install dependencies:

```bash
python3 -m pip install chess==1.11.2
```

Install Stockfish or point the runner to a binary:

```bash
export STOCKFISH_PATH=/path/to/stockfish
```

Smoke-test the runner with its internal random UCI engine:

```bash
bash benchmarks/data/chess-engine-loop/reproduce.sh smoke
```

Evaluate one included generated engine:

```bash
bash benchmarks/data/chess-engine-loop/reproduce.sh eval-included
```

Run a full new model-generation matrix. This invokes Codex and may take time
and API budget:

```bash
python3 benchmarks/runners/chess_engine_loop.py run-matrix \
  --out-dir tmp/chess_engine_loop_rerun \
  --models gpt-5.4-mini gpt-5.5 \
  --modes one_shot hidden_eval_loop cumulative_hidden_eval_loop solver_visible_public_eval \
  --trials 2 \
  --rounds 2 \
  --effort low \
  --timeout-sec 420 \
  --engine-timeout-sec 4 \
  --suites opening_gauntlet advantage_conversion \
  --games-per-fen 1 \
  --movetime-ms 20 \
  --max-plies 40 \
  --stockfish-elo 1320 \
  --stockfish-depth 1
```

`tmp/` is intentionally ignored by git.

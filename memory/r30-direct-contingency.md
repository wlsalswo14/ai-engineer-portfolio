# R30 direct-role contingency (not official evidence)

This note was prepared by the supervising agent after every configured Codex
subscription home returned `CodexQuotaUnavailable` while starting the R30 candidate
arm. It is deliberately outside the arm workspace and is not an undeclared model
input. It must not be treated as a Luna receipt or promotion evidence.

## Call 1: semantic-normal-form transducer

The supplied engine already centralizes state mutation in `make(Position, move)`, but
its semantic seams are implicit. A behavior-preserving normalization should:

1. Add one canonical position-key method covering board, side, castling rights, and en
   passant state; route the transposition table through it without changing key
   semantics.
2. Add explicit helpers for check state, quiet/capture/promotion move classification,
   and state transitions. Do not change evaluation constants, pruning, depth, time
   allocation, or move ordering in this pass.
3. Preserve the exact UCI boundary and complete-file response.
4. Check start-position legal count 20, castling/en-passant/promotion legality,
   make immutability, deterministic fixed-depth behavior, and UCI timeout behavior.

## Call 2: obligation-preserving strength transducer

The highest-leverage general weakness is that every non-root move receives a full
window/full-depth search. This limits completed depth at the frozen move time. Make one
coherent search-efficiency change through the normalized move/state seams:

1. Use principal-variation search: the first ordered move gets the full window; later
   moves get a null window and are re-searched only when they raise alpha.
2. Add conservative late-move reduction only for later quiet, non-promotion moves at
   depth at least 3, outside check, with a mandatory full-depth re-search when the
   reduced result raises alpha.
3. Keep mate scores, TT bounds, legality, check extensions, quiescence, and the hard
   deadline coherent. Do not tune evaluation constants or add opening-specific logic.
4. Validate legal output, deterministic fallback, mate/stalemate handling, tactical
   sanity, and that the reduced/PVS path actually occurs on a general middlegame probe.

If Luna quota remains unavailable and an operator-authorized direct artifact is later
materialized, its provenance must be marked `supervisor_direct_contingency`; it cannot
promote under the frozen Luna-high contract without an official Luna reproduction.

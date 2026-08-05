# Clean R8-baseline vs R20 requalification

Official round names use an offset of 19: internal clean R1 is displayed as R20, internal R2 as R21, and so on. This is a
display-only alias; stored paths, identifiers, artifacts, metrics, and audit records retain their internal clean indices.

This experiment starts a fresh lineage at the last uncontaminated pre-R8 bootstrap champion. Its first and only initial
challenger is the archived R20 loop structure. Both structures start from the same bootstrap engine under the v4 contract:
only three fully valid matched pairs may produce a promotion; an invalid pair is rerun in full up to three attempts and an
exhausted retry budget yields an inconclusive result rather than a win.

Rounds after R20 use `matched-three-diverse-anchor-relative-v5`: current champion, frozen lineage baseline, and a valid
non-representative artifact from the latest promotion are precommitted as three distinct anchors. Per-call token receipts are
aggregated by arm, pair, retry, and round. See `ANCHOR-AND-TOKEN-CONTRACT.md` and `R21-R25-REPORT.md`.

The previous `chess-tier5` workspace remains a preserved research archive and is not used as the authority for this clean
lineage.

## Requalification result

The fixed R20 challenger was promoted as official R20 (internal clean round 1) under
`matched-three-valid-pair-relative-v4`:

- valid-pair result: 3 candidate wins, 0 losses, 0 ties
- candidate median Elo: -148.002
- incumbent median Elo: -214.360
- median delta: +66.358
- promoted package: `package_e7705cfa9eb969f5`
- promoted structure: `loop_d9b6fe59cd5b067b`

Pair 3 attempt 1 was discarded in full because the candidate engine had six benchmark execution failures. Pair 3 attempt 2
reran both arms, produced zero failures on both sides, and was the valid pair used in the final decision.

The current official state is R25 complete. R24 promoted the three-call postbuild independent falsification structure;
R25 did not promote, so R24 remains champion.

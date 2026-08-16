# Cache Transfer League

This directory is a fresh, score-blind Cache Policy campaign. It has no lineage
dependency on any earlier Cache campaign. Its only benchmark authority is the
frozen V3 `cache_policy_scratch` contract in `loopsy_archive`.

Display R0 compares fixed, vocabulary-only translations of the promoted chess
loop topologies displayed as R20, R24, R26, and R30. Each topology receives the
same freshly generated LRU anchor and produces exactly three independent policy
representatives. All policy-producing, policy-analyzing, repair, and finalization
roles run with `gpt-5.6-luna` at `high` reasoning. The single bootstrap architect
call runs with `gpt-5.6-sol` at `max` reasoning and `service_tier="fast"`; it may
translate roles, visibility, hypotheses, and topology language, but it may not
emit policy code or change a call graph.

The phase boundary is fail-closed:

1. `prepare` verifies source identities and the frozen 9-trace fixture hash.
2. `translate` creates score-free fixed-topology Cache contracts.
3. `generate` creates the fresh anchor and the twelve independent policies.
4. `seal` records syntax, interface, deterministic generic-validity checks, and
   immutable hashes for every artifact, then writes one global pre-evaluation
   seal. No frozen evaluator is callable without that seal.
5. `evaluate` acquires the shared heavy-evaluation lock and runs frozen V3 twice
   for every sealed artifact. It requires byte-equivalent normalized replay
   results, zero invalid operations, zero timeouts, and all three valid reps for
   structure eligibility.
6. `finalize` selects by the predeclared median rule, performs the predeclared
   close-result confirmation when needed, and materializes provisional display
   R0.

The initial authorization stopped after the atomic R0 commit. A later explicit
authorization opened exactly display R1 from that immutable R0 champion. R1 is
a three-pair matched structure duel and must stop without opening R2. The R0
contract and atomic receipt remain immutable historical records.

The subsequent user-authorized continuation is fixed by
`EVOLUTION-R2-R5-CONTRACT.json`: it opens R2 from the immutable stopped R1 state,
derives every later proposal mode from the prior atomic outcome, completes
exactly R2 through R5, and stops with Cache R6 unopened. Each round retains the
same score-blind Sol-architect/Luna-inner matched-duel boundary and frozen V3
promotion contract.

A further explicit continuation is bound by `EVOLUTION-R6-R11-CONTRACT.json`.
It starts from the immutable R5 atomic checkpoint, derives R6 as persistent
counter-hypothesis mode, derives every subsequent mode from the prior atomic
outcome, completes exactly R6 through R11, and stops without opening R12.

Run from the repository root:

```powershell
python experiments/cache-transfer-league/run_bootstrap.py prepare
python experiments/cache-transfer-league/run_bootstrap.py translate
python experiments/cache-transfer-league/run_bootstrap.py generate
python experiments/cache-transfer-league/run_bootstrap.py seal
python experiments/cache-transfer-league/run_bootstrap.py evaluate
python experiments/cache-transfer-league/run_bootstrap.py finalize
python experiments/cache-transfer-league/run_bootstrap.py verify
```

`evaluate` must be launched only after the chess campaign explicitly grants GO.
It serializes its complete scoring and confirmation section with
`experiments/.heavy-evaluation.lock.json`.

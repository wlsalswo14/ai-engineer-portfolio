# R1000 campaign operating contract

## Objective

Advance the official clean lineage from display R29 to display R1000. The display
round is `internal round + 19`, so the terminal internal round is 981.

## Fixed controls

- Run exactly one evolution experiment at a time.
- Use the independent Sol structure-design subagent at `max` reasoning effort.
- Keep Luna `high` for every evolved-loop execution call.
- Keep ChessBench100 Tier 5, the evaluator, Elo calculation, anchor policy, and
  promotion rule frozen.
- Use bounded early adjudication. Never pass `--force-complete-pairs` to a campaign.
- Treat quota, transport, timeout, or missing evidence as retryable/invalid evidence,
  not as a structural loss.
- Never use benchmark hard-coding, engine hyperparameter tuning as the structural
  hypothesis, or replicated best-of-N candidates.

## Execution

```powershell
python run.py run-until --target-display-round 1000 --retry-delay-seconds 30
```

The campaign executes one `run_round()` call at a time. It does not overlap rounds.
Transient failures remain active and are retried indefinitely after a bounded delay.

## Recovery files

- `experiments/chess-tier5-clean/workspace/campaign-control.json`: current PID, target,
  official internal/display round, status, and last error.
- `experiments/chess-tier5-clean/workspace/campaign-events.jsonl`: append-only campaign
  lifecycle and per-round completion events.
- `experiments/chess-tier5-clean/workspace/campaign.lock.json`: live single-campaign
  ownership. A dead owner's lock is preserved under
  `workspace/archive/stale-campaign-locks/` before recovery.
- `experiments/chess-tier5-clean/workspace/state.json`: authoritative evolutionary
  state. A round is official only after this state advances and its round summary and
  archive record are present.

## Monitoring and adjudication

Read the small control file and latest campaign event first. Inspect the current round
summary, pair summary, receipts, and process tree only when needed. Do not dump entire
actor responses. Promotion requires the frozen matched-pair contract. A completed
early batch is valid only when the remaining pair cannot change the relevant promotion
or development decision.

Do not mark the active goal complete before display R1000 is present in authoritative
state, its R1000 summary/archive record is verified, tests pass, and no campaign or
child model process remains.

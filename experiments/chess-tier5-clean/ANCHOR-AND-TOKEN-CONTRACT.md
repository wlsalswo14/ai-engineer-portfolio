# Diverse-anchor and token-accounting contract

Each round precommits three anchor engines before either structure is run:

1. the current champion's representative engine;
2. the frozen lineage bootstrap engine;
3. a non-representative valid engine from the most recent promoted batch.

Within a pair, incumbent and candidate receive the exact same anchor and matching metrics. Across the batch, the three
anchors must be source-diverse whenever the lineage contains enough distinct valid artifacts. The panel is persisted at
`evaluation/anchor-panel.json` and cannot change during a resumed round. Promotion refreshes the current and recent-promotion
slots; stagnation leaves the panel stable.

Token accounting is observational and does not affect promotion. Every accepted and invalid attempt contributes its actual
model-call usage. The round ledger separates independent Sol max structural-architect usage from Luna high internal-loop usage and reports both
raw and effective totals:

```text
total tokens     = input tokens + output tokens
effective tokens = input tokens - cached input tokens + output tokens
```

Reasoning output tokens are reported separately but are not added again because they are a subset of output tokens.
`proposal_structural_architect` is the canonical proposal key. `proposal_sol_max` and the historical
`proposal_sol_xhigh` key are non-additive aliases for compatibility with existing round readers.

# R26–R28 search-cycle report

Official R26 through R28 correspond to internal clean rounds R7 through R9. All used
`matched-three-diverse-anchor-relative-v5` and the frozen ChessBench100 tier-5 evaluator.

## Outcomes

| Round | Search mode | Candidate capability | Result | Promoted |
|---:|---|---|---|---|
| R26 | local refinement | causal attribution of failure to exact rollback delta | 1W–0L–2T | yes |
| R27 | emergent 1 | causal-dead-end strategy substitution | 1 valid win; next pair exhausted invalid retries | no; inconclusive |
| R28 | emergent 2 | evidence-conditioned runtime semantic arbitration | 0W–2L; irreversible early rejection | no |

R26 promoted `package_164862893ef916a4`, structure `loop_2c6ee2e0a1ec021b`, with representative engine Elo
`-105.297`. R27 and R28 did not promote, so that package remains champion.

## Pair evidence

R27 pair 1 was a candidate win (`-101.579` versus `-128.134`). Pair 2 exhausted all three attempts because accepted
valid arms could not be obtained in the same attempt; the batch ended inconclusive without pair 3.

R28 pair 1 was a candidate loss (`-143.959` versus `-105.297`). Pair 2 attempt 1 was discarded after an incumbent public
UCI smoke failure. Attempt 2 was valid and also a candidate loss (`-245.114` versus `-152.084`). A second loss made
promotion irreversible, so pair 3 was not run.

## Effective token accounting

| Round | Sol proposal | Luna internal loop | Invalid retry spend | Round total |
|---:|---:|---:|---:|---:|
| R26 | 11,500 | 986,018 | 220,392 | 997,518 |
| R27 | 11,972 | 1,091,797 | 820,366 | 1,103,769 |
| R28 | 13,123 | 740,230 | 237,117 | 753,353 |
| **Total** | **36,595** | **2,818,045** | **1,277,875** | **2,854,640** |

Invalid retry spend is a subset of Luna internal-loop spend and is not added again to the round total.

## Next state

The two local rounds were consumed even though R26 promoted. Both distinct emergent attempts then failed to promote.
The next official round is R29 in `counter_hypothesis` mode, which persists until a promotion occurs.

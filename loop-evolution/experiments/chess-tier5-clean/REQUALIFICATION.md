# R20 clean requalification audit

The last uncontaminated pre-R8 bootstrap loop was initialized as clean round 0. The archived R20 loop structure was then run
as a fixed challenger from the same engine anchor. No new structural proposal was generated for this comparison.

## Contract

- Protocol: `matched-three-valid-pair-relative-v4`
- Three fully valid matched pairs are required.
- An invalid arm invalidates the whole attempt; it cannot award a win to the other arm.
- The entire pair is rerun, up to three attempts.
- Promotion requires candidate wins greater than losses, candidate median Elo greater than incumbent median Elo, and zero
  invalid arms in the three accepted pairs.

## Accepted results

| Pair | Incumbent Elo | R20 candidate Elo | Verdict | Accepted attempt |
|---:|---:|---:|---|---:|
| 1 | -350.025 | -148.002 | candidate win | 1 |
| 2 | -214.360 | -105.297 | candidate win | 1 |
| 3 | -200.054 | -160.370 | candidate win | 2 |

Candidate median Elo was `-148.002`; incumbent median Elo was `-214.360`; the delta was `+66.358`.

Pair 3 attempt 1 is retained as audit evidence but was excluded from the decision. Its candidate completed 100 games with
six candidate-process failures, so v4 marked the attempt invalid and discarded both arms. Attempt 2 regenerated and
reevaluated both arms with zero failures.

## Decision

R20 was promoted as clean round 1:

- Package: `package_e7705cfa9eb969f5`
- Structure: `loop_d9b6fe59cd5b067b`
- Organization: solo, one call
- Representative engine: pair 1 candidate, Elo `-148.002`

The previous `experiments/chess-tier5` lineage is preserved for research and audit but is not authoritative.

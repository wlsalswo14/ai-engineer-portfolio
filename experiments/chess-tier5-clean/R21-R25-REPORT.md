# R21–R25 diverse-anchor and token report

Official R21 through R25 correspond to internal clean rounds R2 through R6. All rounds used
`matched-three-diverse-anchor-relative-v5`. Each pair gave incumbent and candidate the same anchor; the three batch anchors
were the current champion, frozen lineage baseline, and a valid non-representative artifact from the latest promoted batch.

## Round outcomes

| Round | Candidate structure | Calls | Result | Candidate median | Incumbent median | Promoted |
|---:|---|---:|---:|---:|---:|---|
| R21 | provenance-block terminal compression | 1 | 2W–1L–0T | -177.479 | -160.370 | no |
| R22 | provisional compression with terminal restoration | 1 | 1W–2L–0T | -200.054 | -120.412 | no |
| R23 | precommitted forensic handoff | 2 | 0W–2L–0T | n/a | n/a | no; irreversible early rejection |
| R24 | postbuild independent falsification and bounded integration | 3 | 2W–0L–1T | -105.297 | -164.577 | yes |
| R25 | post-mutation certificate gate | 5 | 0W–1L–2T | -105.297 | -105.297 | no |

R24 promoted package `package_c8d1a400baa5761a` and structure `loop_bed92958056c5bfb`. Its representative engine Elo is
`-105.297`. R25 did not promote, so this remains the champion after R25.

## Effective token accounting

Effective tokens are `(input - cached input) + output`. Reasoning tokens are already a subset of output and are not added a
second time. Invalid and interrupted attempts remain part of actual spend.

| Round | Sol proposal | Luna incumbent | Luna candidate | Luna combined | Invalid/interrupted spend |
|---:|---:|---:|---:|---:|---:|
| R21 | 9,725 | 82,759 | 109,827 | 192,586 | 50,909 |
| R22 | 8,742 | 120,426 | 118,744 | 239,170 | 89,299 |
| R23 | 9,938 | 47,201 | 185,106 | 232,307 | 0 |
| R24 | 12,239 | 101,062 | 574,880 | 675,942 | 255,524 |
| R25 | 13,046 | 358,870 | 528,052 | 886,922 | 0 |
| **Total** | **53,690** | **710,318** | **1,516,609** | **2,226,927** | **395,732** |

Grand effective usage including Sol proposals was `2,280,617` tokens. Raw usage, before subtracting cached input, was
`11,198,377` tokens: `103,610` Sol plus `11,094,767` Luna. Invalid or interrupted attempts consumed `395,732` effective
tokens (`1,906,644` raw tokens).

## Anchor-level outcomes

| Round | Anchor | Verdict | Incumbent Elo | Candidate Elo | Attempts | Inc effective | Cand effective | Invalid effective |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| R21 | current champion | loss | -160.370 | -245.114 | 1 | 18,829 | 27,287 | 0 |
| R21 | frozen baseline | win | -256.130 | -177.479 | 1 | 20,895 | 31,204 | 0 |
| R21 | promotion alternate | win | -156.206 | -139.951 | 2 | 43,035 | 51,336 | 50,909 |
| R22 | current champion | win | -256.130 | -224.267 | 1 | 32,591 | 24,060 | 0 |
| R22 | frozen baseline | loss | -120.412 | -200.054 | 2 | 42,995 | 48,093 | 43,762 |
| R22 | promotion alternate | loss | -105.297 | -168.829 | 2 | 44,840 | 46,591 | 45,537 |
| R23 | current champion | loss | -219.274 | -250.568 | 1 | 21,907 | 90,648 | 0 |
| R23 | frozen baseline | loss | -112.803 | -214.360 | 1 | 25,294 | 94,458 | 0 |
| R24 | current champion | win | -168.829 | -120.412 | 1 | 21,489 | 91,228 | 0 |
| R24 | frozen baseline | win | -164.577 | -94.211 | 2 | 20,663 | 231,782 | 118,742 |
| R24 | promotion alternate | tie | -105.297 | -105.297 | 2 | 58,910 | 251,870 | 136,782 |
| R25 | current champion | tie | -105.297 | -105.297 | 1 | 99,463 | 139,809 | 0 |
| R25 | frozen baseline | tie | -94.211 | -94.211 | 1 | 143,056 | 143,951 | 0 |
| R25 | promotion alternate | loss | -120.412 | -148.002 | 1 | 116,351 | 244,292 | 0 |

“Win/loss/tie” is always from the candidate's perspective.

## Main observations

- Anchor diversity changed the conclusion in several rounds. R21 won on baseline and alternate but lost on the current
  champion anchor, while R22 showed the opposite pattern on its first pair and failed the other two.
- R24 found a transferable improvement: it won on current champion and frozen baseline and tied on the alternate.
- R25's extra post-mutation audit mostly collapsed to the anchor behavior: two exact Elo ties, then a loss on the alternate.
  It spent more tokens without improving the median, so it was correctly rejected even though token cost was not a gate.
- Invalid and interrupted work represented about 17.8% of Luna effective usage. Recording it exposed a material reliability
  cost that Elo alone did not show.

Machine-readable ledgers live at each internal round's `evaluation/token-accounting.json`; the per-round frozen anchor lists
live at `evaluation/anchor-panel.json`.

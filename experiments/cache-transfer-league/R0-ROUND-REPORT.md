# Cache Transfer League — display R0

Fresh bootstrap only. No prior Cache lineage, artifacts, scores, or error notes were used.

Frozen benchmark: `cache_policy_scratch`, seed `20260605`, scale `3`, 9 traces, fixture `793cbd7e5c04e896650ebc713fc29654fc63cf5fe1aaba15f6f6149d11795d87`.

| Fixed source topology | Rep 1 | Rep 2 | Rep 3 | Median | All valid |
|---|---:|---:|---:|---:|:---:|
| R20 | 82.0738 | 82.0738 | 86.3655 | 82.0738 | yes |
| R24 | 66.7525 | 66.7525 | 66.7525 | 66.7525 | yes |
| R26 | 83.3551 | 66.7525 | 66.7525 | 66.7525 | yes |
| R30 | 81.8930 | 0.0000 | 77.8732 | 77.8732 | no |

Anchor replay score: `66.7525`; valid/deterministic: `True`.

Provisional R0 selects fixed R20 topology, representative 1, artifact `294fb24343b8694d908efd6141fad01df3eb5543af329f7f473c0abbace03a60`.

Close confirmation (0.25 absolute median band): triggered `False`, passed `True`.

Campaign stop is final at display R0. Cache R1 was not opened.

# Current work

Goal: advance the clean loop-evolution lineage through display R1000 without ending
the active turn prematurely.

Current authoritative state: internal round 16 / display R35. The active champion is
`package_a9dd70e3fc84f08d`, structure `loop_b51c38b8268a6c22`.

Implementation and validation are complete for the independent Sol structure-design
subagent at `max` and the sequential persistent campaign driver. The incomplete
internal r0011 created by the older xhigh architect was archived without adjudication
at `workspace/archive/aborted-rounds/r0011-20260805T221752`.

Launch command after validation:

```powershell
python run.py run-until --target-display-round 1000 --retry-delay-seconds 30
```

Primary recovery evidence is `workspace/campaign-control.json`, followed by the last
line of `workspace/campaign-events.jsonl`, `workspace/state.json`, and the current
round's small summary files. Never overlap a second campaign.

The persistent campaign PID is `18632` and is currently attempting display
R36/internal r0017 in `counter_hypothesis` mode. R35's independent counter family
`Persistent Single-Actor Experimental Construction` was valid but lost 0W/2L and
reached only 86.36% of the incumbent score rate, so it was not retained for
development. Codex CLI quota/backend errors remain retryable. The independent Sol max
collaboration subagent is preparing the R36 counter-family proposal under
`workspace/manual-proposals/r0017/` without racing the live generation directory.
Direct role substitutions must keep
`official_runtime_policy_reproduced=false` and preserve the declared call topology.

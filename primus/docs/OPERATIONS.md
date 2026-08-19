# Operations

## First installation

Run `scripts/install.ps1`. It installs the local package, initializes task banks, imports inaugural champions, quarantines legacy structures, runs the integrity doctor, and runs the full test suite. Re-running it is safe: it never replaces a newer active champion with an inaugural one.

## Normal operation

Use `primus loop start <domain>`. A stopped run is resumed by `primus loop resume <domain>`. Never delete a run directory to retry it; completed model calls are immutable inputs to resume.

Use `primus status` for pointers and state. Use `primus audit` for object/receipt integrity. Use `primus doctor` before a long campaign or after changing an evaluator binary, model account, task bank, or path.

Before a campaign, inspect its staged worst-case cost. For example, `primus cost chess --candidate-calls 4` shows cumulative portfolio, screening, and certification calls/games. `primus cost cache --candidate-calls 2` includes its two-candidate public probe. A public loser stops immediately; hidden certification is never generated speculatively.

## Hidden-bank exhaustion

Certification case selections are one-use by semantic fingerprint, not by ID. Primus checks availability before spending model calls and fails closed when a selection would repeat. Add genuinely new hidden cases or a new pinned suite, update the certification taskset, then run `primus doctor`. Renaming or reordering duplicate cases is not a valid refresh. The doctor reports the semantic case count and estimated selection capacity for each domain.

## Adding a domain

Add the domain ID to `config/system.json`, create `config/domains/<id>.json`, provide public and certification tasksets, and point `adapter` to either a built-in name or `package.module:AdapterClass`. The adapter must implement the common `DomainAdapter` contract. Import one bootstrap champion before starting a round. Core CLI, status, doctor, storage, and orchestration discover the domain from configuration.

## Recovery

- Quota or transport failure: leave evidence in place and run `primus loop resume <domain>`.
- Heavy lock after a crash: the lease code quarantines it only if its PID is dead or it is older than the configured stale window.
- Digest mismatch: do not edit the stored object. Restore the authoritative source or intentionally create and review a new pinned configuration.
- Evaluator failure: the candidate does not promote. Correct infrastructure, then resume only if the round has not entered a failure terminal.

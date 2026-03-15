# Public Repo Pilot — Rescue & Backfill

The original deterministic 10-repo pilot subset stalled because only one workspace validated end-to-end. Dozens of repos were blocked by missing Python packaging modules, absent Node package managers, or command-inference gaps. Rather than forcing that brittle subset to succeed, the pilot now uses a “rescue + backfill” loop to automatically heal fixable repos and backfill replacements from the larger CGCS seed pool.

## Why rescue and backfill?

- **Environment issues dominate:** most failures were due to missing `pip/setuptools/wheel/build`, disabled corepack managers (yarn/pnpm), or optional build steps that were over-enforced. These are safe to fix automatically.
- **Seed pool is larger than 10 repos:** we already have 82 candidates in `cgcs_seed_pool.jsonl`. When a repo is truly hard-blocked (native deps, broken tests, unsupported layout), it is faster to pull a fresh candidate than to keep retrying.
- **Research needs more than 1 runnable repo:** the benchmark, strict dataset, and eval pack all depend on having multiple runnable workspaces and seeded tasks. Targeting 5–8 validated repos plus 10–20 tasks provides enough diversity to re-run all experiments.

## What counts as rescueable?

Rescue attempts currently cover:

1. **Python packaging bootstrap** — installs/refreshes `pip`, `setuptools`, `wheel`, and `build` (via `python -m pip install --upgrade ...`) and re-runs validation.
2. **Node package manager activation** — inspects `package.json` for the `packageManager` field or lockfiles, then enables pnpm/yarn via `corepack` (or falls back to npm).
3. **Build optionality** — when build scripts are absent but tests exist, the validator classifies the repo as `runnable_without_build` so it still feeds seeding.

If these safe steps succeed, the repo moves into the validated pool. If they fail, or the repo is missing commands/tests entirely, it is marked `hard_blocked` and queued for replacement.

## Replacement strategy

- Draw candidates from `cgcs_seed_pool.jsonl`, excluding repos already attempted or hard-blocked.
- Maintain diversity across languages/owners/build systems/test frameworks using the same scoring heuristics as the initial subset.
- Expand up to `max_pilot_size` (default 20) while targeting at least 5 validated repos.

Attempt and replacement logs are written to `data/public_repos/pilot/pilot_attempt_log.jsonl` and summarized under `reports/decomposition/public_repo_pilot/{rescue,expansion}_debug.md`.

## Complete pilot pipeline

`scripts/public_repos/run_complete_public_repo_pilot.py` orchestrates:

1. **Rescue/backfill:** `rescue_and_expand_pilot.py` heals or replaces repos until enough validate.
2. **Seeding:** `generate_seeded_repair_tasks.py` seeds tasks from both `runnable` and `runnable_without_build` repos.
3. **Benchmark runs:** `run_public_repo_pilot.py` executes `contract_first`, `failure_mode_first`, and `cgcs` strategies on the seeded tasks.
4. **Strict dataset:** `scripts/build_cgcs_dataset.py --strict` rebuilds the pilot rows and enforces the “usable row” rules. If usable_rows == 0, the orchestrator fails immediately and writes a blocker report.
5. **Eval pack:** when usable rows exist, `build_public_repo_eval_pack.py` produces non-placeholder eval items for OpenAI harnesses.

This loop repeats automatically until the targets are hit or the seed pool is exhausted, providing enough validated repos to keep the research pipeline moving.

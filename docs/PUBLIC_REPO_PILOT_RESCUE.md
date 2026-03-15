# Public Repo Pilot Rescue Checklist

This runbook captures the new guard rails added to keep the public-repo pilot alive when traces or JS/TS workspaces go sideways.

## Strict Trace Fields
- Every solve/repair round now emits a **strict payload** at runtime. The harness rewrites `logs/edits_round*.json` with the augmented fields _and_ appends each payload to `logs/strict_round_traces.jsonl`.
- Required keys — `contract_items`, `active_clause_id`, `regression_guard_ids`, `witnesses`, `raw_edit_payload`, `candidate_files`, `row_quality` — are written even when the value is logically empty (e.g., `[]` for witnesses when none were detected).
- Non-clause strategies fall back to stable clause IDs:
  - single-contract repos reuse the only clause ID.
  - otherwise a synthetic `strategy_default_clause` keeps the field non-empty.
- `row_quality` now standardises diagnostics: `contract_quality`, `active_clause_source`, `witness_count`, `payload_present`, `payload_parse_ok`, `candidate_file_count`, `strategy_mode`, `used_fallback`.
- If a strict payload is missing, `run_public_repo_pilot.py` immediately marks the run as `trace_missing_fields` so the rescue loop can swap the repo out before dataset construction.

## Package Manager + Corepack Awareness
- Workspace planning consumes `package.json.packageManager` and `workspace:*` dependencies. Yarn/PNPM repos _never_ default back to npm even when lockfiles are absent.
- The plan records `package_manager_spec` (e.g., `yarn@3.6.0`) so validation can activate the matching runtime. Safe bootstrap mode now prepends:
  1. `corepack enable`
  2. `corepack prepare <pm>@<version> --activate`
- Validation refuses to run corepack commands when the binary is absent. Those repos land in the pilot report as `missing_corepack` with `rescueable=true`, making it obvious that the fix is a runner upgrade rather than seeding a new repo.

## Node Engine & npm Integrity Checks
- `package.json.engines.node` is parsed before any install/build/test step. When the workspace requires a newer runtime than the runner exposes, the row is marked:
  - `failure_category = node_engine_mismatch`
  - `hard_blocked = true`
  - `hard_block_reason = node_engine_mismatch`
  - `engine_requirements` + `actual_runtime_versions` record the exact numbers for replacement triage.
- npm install failures gain a bounded fallback:
  - peer-dependency conflicts -> `npm install --legacy-peer-deps`
  - repeated integrity errors -> `npm cache clean --force` then a single retry
- Every fallback attempt is logged in `rescue_actions_attempted`. When integrity issues persist the row becomes a hard block (`hard_block_reason = npm_integrity_failure`), signalling that the repo should leave the pilot subset.

## Validation Output for Replacement Decisions
- Each validation record now includes:
  - `hard_blocked` / `hard_block_reason`
  - `rescueable`
  - `rescue_actions_attempted`
  - `package_manager`, `package_manager_spec`
  - `engine_requirements`
  - `actual_runtime_versions`
- Examples:
  - **node_engine_mismatch** → `hard_blocked=true` so the scheduler swaps in a replacement repo unless the environment is upgraded.
  - **workspace npm misuse** → validation overrides the command automatically, sets `rescueable=true`, and records the override in `rescue_actions_attempted`.
  - **missing corepack / yarn / pnpm** → `rescueable=true` because tooling installs fix the issue without touching the repo snapshot.

Use this document alongside `scripts/public_repos/validate_cgcs_workspaces.py` when auditing pilot readiness. If a repo is still blocked after these automatic rescues, the pilot controller now emits enough metadata to explain _why_ and how to replace it deterministically.

# Public Repo Workspace Normalization

Our pilot repos span Python packages, JS/TS monorepos, and JVM projects. Most validation failures were not real build regressions — they were caused by missing packaging tools, naive command inference, or environments that tried to run `python -m build` without installing the `build` module. The new normalization layer makes those gaps explicit and provides reproducible remediation steps.

## End-to-end pipeline

1. **Workspace manifest enrichment** — `scripts/public_repos/prepare_workspaces.py` now records the detected language bucket, package manager, build system, command inference source, bootstrap commands, and required tools for each repo. The information lives in `data/public_repos/workspace_manifest.jsonl`.
2. **Workspace bootstrap planning** — `src/public_repos/pilot/workspace_bootstrap.py` inspects build files + `package.json` scripts (when present) and emits:
   - install/build/test commands that match the lockfile or framework
   - safe bootstrap commands for Python packaging gaps (ensurepip + `pip install --upgrade pip setuptools wheel build`)
   - required CLI tooling (poetry, pnpm, mvn, java, …)
3. **Validation executor** — `scripts/public_repos/validate_cgcs_workspaces.py` uses the manifest plan, optionally runs bootstrap commands (`--bootstrap-mode safe`), skips build steps only when explicitly instructed (`--skip-build-if-missing`), and produces structured verdicts (`runnable`, `runnable_without_build`, `blocked_by_environment`, `blocked_by_dependency_resolution`, `blocked_by_command_inference`, `unsupported_repo_type`).
4. **Failure debugging** — `scripts/public_repos/debug_workspace_failures.py` turns the validation JSONL file into aggregated stats + remediation buckets to focus on rescuable repos first.

## Environment vs. repo flakiness

* **Environment gap:** missing Python packaging modules, package managers (`pnpm/yarn`), JVM toolchains, or bootstrap commands that were not allowed to run. Recognised via `failure_category` such as `missing_python_build_module`, `missing_node_package_manager`, `bootstrap_required`, or `missing_maven`, and classified as `blocked_by_environment`.
* **Command inference gap:** build/test commands could not be inferred or scripts are absent. These appear as `missing_build_command`, `missing_test_command`, or `command_inference_error`, and surface as `blocked_by_command_inference`.
* **Repo flakiness:** build/test commands ran but failed. Logged as `build_script_failed` / `test_command_failed` which keeps provenance through `stdout_snippet` and `stderr_snippet`.

The normalization layer keeps these buckets separate so we can confidently rescue environment-only failures without masking real regressions.

## Safe bootstrap mode

Use `--bootstrap-mode safe` when running `validate_cgcs_workspaces.py`. The validator will:

1. Ensure `pip` exists (`python -m ensurepip --upgrade` when needed).
2. Install missing `pip`, `setuptools`, `wheel`, or `build` modules in place.
3. Respect the manifest’s bootstrap command list and log what was executed.

If bootstrap is disabled but required, the validator now returns `failure_category = missing_python_build_module` (or similar) instead of a vague install failure, making it clear that only a safe dependency install is blocking the repo.

## Optional build phase and verdicts

Some repos expose only a test command (e.g., pure libraries with no bundler). Passing tests without a build step now produce `final_verdict = runnable_without_build`. Fully passing install/build/test results remain `runnable`. Both verdicts are eligible for seeding when `--allow-runnable-without-build` is used.

If no test command exists, the validator reports `blocked_by_command_inference` with `failure_category = missing_test_command`. Missing build commands only block the repo when `--skip-build-if-missing` is *not* set.

## Failure debugging workflow

1. Run validation with the safe bootstrap command from the Makefile target or the explicit CLI:
   ```bash
   PYTHONPATH=. python scripts/public_repos/validate_cgcs_workspaces.py \
     --subset data/public_repos/pilot/cgcs_pilot_subset.jsonl \
     --workspace-manifest data/public_repos/workspace_manifest.jsonl \
     --out-dir data/public_repos/pilot \
     --bootstrap-mode safe \
     --skip-build-if-missing \
     --timeout-seconds 300
   ```
2. Aggregate failures:
   ```bash
   PYTHONPATH=. python scripts/public_repos/debug_workspace_failures.py \
     --input data/public_repos/pilot/workspace_validation.jsonl \
     --out-dir data/public_repos/pilot
   ```
3. Inspect `reports/decomposition/public_repo_pilot/workspace_failure_debug.md` to answer:
   - Which repos are blocked only by bootstrap gaps?
   - Which repos need better command inference?
   - Which repos are genuinely unsupported?

Use the `safe_bootstrap_candidates` list to prioritise quick fixes (installing `build`, `pip`, `setuptools`, `wheel`, or missing Node package managers). Then tackle `command_inference_candidates` (missing scripts) before concluding that a repo is unsupported.

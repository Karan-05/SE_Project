# Real Evaluation Summary

## Latest run: `real_eval_20260308_194805`
- **Scope** – 1 curated benchmark task (`array_sum`) evaluated with `contract_first` + mock model via `experiments/run_real_task_eval.py --task-ids array_sum --limit 1`.
- **Outcomes** – `PASS_ALL_TESTS=1`, `partial/test/build failures=0` (`results/real_eval/metrics.csv`).
- **Artifacts** – Per-task results at `results/real_eval/runs/real_eval_20260308_194805/per_task_results.jsonl`, decomposition trace at `.../decomposition_traces.jsonl`, and solution code under `.../tasks/array_sum__contract_first_mock-model/solution.py`.
- **Paper tables** – `reports/ase2026_aegis/real_eval_table_main.csv` summarises run-level counts (success_rate=1.000), while `real_eval_table_by_category.csv` records the algo-coding category breakdown.

## Harness status
1. `experiments/run_real_task_eval.py` now drives the evaluation (benchmark JSON → `TaskManifest` → `RealTaskRunner` → JSONL + tables).
2. Results automatically roll into aggregate files:
   - `results/real_eval/metrics.csv` – per-run counts.
   - `results/real_eval/per_task_results.jsonl` – concatenated per-task logs for downstream analytics.
3. Each run records decomposition summaries (subtasks/tests/contract snapshots) so we can study planner behavior alongside executable outcomes.

## Next steps
- Expand beyond a single benchmark task by:
  - Running the full 50-task benchmark JSON to baseline the harness.
  - Carefully onboarding the 39 partially validated Topcoder tasks (with the new manifest filters) while flagging synthetic/statement-derived tests.
- Add metric exports the user requested (real_eval_table_main/by_category already exist; upcoming work will populate `real_eval_table_main.csv` with additional strategies/models).

## Real Topcoder SRM benchmark (2026-03-11)
- Command: `PYTHONPATH=. LLM_PROVIDER=openai LLM_MODEL=gpt-4.1-mini python scripts/prepare_real_repo_benchmark.py --mode real_world_research --strategies contract_first,failure_mode_first`
- Scope: 4 SRM API tasks from the `tc-template-node-postgres` snapshot (see `experiments/real_repo_tasks/topcoder/`).
- Preflight/setup: all repos passed `npm ci --no-audit --no-fund` prep; logs baked into `reports/decomposition/real_world/real_repo/runs/**/logs/setup_summary.json`.
- Outcomes: both strategies exhausted repairs without landing an edit (`pass_rate=0`, `localization_precision=0`, `ground_truth_precision=0` in `reports/decomposition/real_world/real_repo/summary.md`). Edit logs show the root cause—LLM replies lacked the new JSON edit format—so the solver has been updated to emit explicit repo-edit instructions before the next run.
- Teacher/oracle baseline: the same helper now runs an `oracle_teacher` strategy that applies each task’s `ground_truth.patch` before running the Mocha suites. This demonstrates solvability once the repo snapshot matches the patches (if the repo has drifted, the baseline logs `patch_failed`, which is still useful for diagnosing drift).

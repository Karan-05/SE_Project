# Real vs Simulator Gap

## Simulator baseline
- Workflow-control studies (`experiments/run_workflow_rl.py`, `results/workflow_rl/*.csv`) report success rates in the 0.65–0.85 band for synthetic episodes, with `contract_first` + teacher hybrids reaching >0.8 reward in mock settings (see `reports/ase2026_workflow_rl/table_main.csv`).
- Decomposition sweeps built on curated benchmarks (`reports/decomposition/strategy_comparison.csv`) routinely exceed 90% pass-rate because they replay the same deterministic unit tests.

## Real evaluation status
- The new harness (`experiments/run_real_task_eval.py`) currently exercised 1/50 benchmark tasks (array_sum) and produced a single `PASS_ALL_TESTS` result. As we scale to the entire benchmark JSON we expect similar behaviour because the tasks are identical to those used in decomposition sweeps.
- None of the 22,023 Topcoder challenges has a reproducible repository/test harness yet; even the 39 partially validated tasks rely on synthetic tests that only confirm consistency with mocked contracts.

## Gap & roadmap
1. **Coverage** – Simulator runs claim success over thousands of synthetic episodes, but the real harness only has 50 trustworthy tasks today. The gap is at least 22,000 tasks wide until we attach repositories/tests to genuine challenges.
2. **Definition of success** – Simulator success rewards planner choices even when no real code runs. Real evaluation demands executable artifacts (`results/real_eval/metrics.csv`), so we must track both; the harness now logs statuses (`PASS_ALL_TESTS`, `TEST_FAIL`, etc.) to make the distinction explicit.
3. **Next steps to close the gap**:
   - Run the harness on all 50 benchmark tasks to establish a ground-truth baseline.
   - Prioritise a handful of Topcoder challenges where repositories/tests can be reconstructed (e.g., from archived submissions or open-source mirrors).
   - Once the executable subset grows, compare simulator policies vs real outcomes by joining `results/workflow_rl/*.csv` with `results/real_eval/per_task_results.jsonl`.

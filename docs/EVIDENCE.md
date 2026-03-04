# Evidence + Reproduction Guide

## Tower-of-Hanoi Benchmark
- **Command:** `make toh_benchmark` (runs `python -m src.benchmarks.toh.run --out_dir reports/llm_bench/tower_of_hanoi --seeds ${SEEDS}`).
- **Outputs:** `tower_of_hanoi_runs.csv`, `tower_of_hanoi_summary.csv`, `fig_success_rate.png`, `fig_pareto.png`, `table_toh.tex`, and `metadata.json` under `reports/llm_bench/tower_of_hanoi`.
- **Token proxy:** word-count of planner prompts + responses per move (recorded via `TOKEN_PROXY` in metadata).
- **Claims supported:** long-horizon success rates vs disk count, token-efficiency Pareto frontier, decomposition strategy comparisons.

## Regression Evaluation
- **Command:** `make regression_eval` (runs `python -m src.regression.run_regression --out_dir reports/regression --seed 42` inside the project venv).
- **Outputs:** `regression_metrics.json`, `preds_test.csv`, `fig_scatter_submissions.png`, `fig_scatter_winning_score.png`, `table_regression.tex`, `metadata.json`.
- **Claims supported:** quantitative MAE/RMSE/R² for predicting submission count + winning score, scatter/residual diagnostics.

## End-to-End Ablations
- **Command:** `make end_to_end_eval` (runs `python -m src.experiments.run_end_to_end --config configs/end_to_end.yaml --out_dir reports/end_to_end --seeds ${SEEDS}`).
- **Outputs:** `runs.jsonl`, `summary.csv`, `fig_ablation_kpis.png`, `table_end_to_end.tex`, `metadata.json`.
- **Claims supported:** failure/starvation/avg-reward/win-rate trade-offs across ablations (full, no-graph, no-RL, no-multi-agent, predictor-only) with 95% bootstrap CIs.

## Compiled Paper Artifacts
- **Command:** `make final_artifacts` (runs `python -m src.final.compile_paper_artifacts --out_dir reports/final --seed 42`).
- **Outputs:** supervised summary CSV/table/figure, RL CI tables + figure, cost-frontier figure/table, integrated ablation figure/table, and `metadata.json` under `reports/final`.
- **Claims supported:** stitched tables/plots for supervised baselines, RL rollouts, decomposition frontier, and end-to-end comparisons ready for appendix use.

## End-to-End Artifact Pack
- **One-shot rebuild:** `make paper_artifacts` sequentially runs ToH, regression, ablations, and final compilation, then prints every report directory for quick copy into the paper appendix.
- **Reference docs:** run `make docs_reference` whenever the code changes to regenerate `docs/reference`. Pair that with this file and `docs/ARCHITECTURE.md` so that any new ChatGPT session can trace each CLI to the exact modules/functions it exercises.

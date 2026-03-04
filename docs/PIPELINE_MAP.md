# Pipeline Map

## Data + Features
- `make preprocess` → `python -m src.data.preprocess` converts `data/raw/*.csv` into parquet artifacts (tasks, workers, market) under `data/processed/`.  
- Learned text/graph embeddings live under `embeddings/` and are consumed by both supervised models and decomposition strategies via `src.models.embeddings`.

## Supervised Outcome Prediction
- Entry point `train_supervised.py` (target `make train_supervised`).
- Uses `src.models.supervised.SupervisedExperiment` with configs from `src.config.SupervisedConfig`.
- Outputs metrics to `reports/tables/supervised_metrics_*.csv` per feature mode (text_only / text_metadata / text_time / multimodal).  
- Ablations orchestrated via `run_ablation` and logged under `reports/tables/` + plots in `reports/figs/`.

## RL Simulation & Allocation Agents
- `make decomp_rl` / `make decomp_rl_seeds` → `src.decomposition.runners.run_rl_integration`.
- Builds Gymnasium env (`src.rl.env.CompetitionEnv`) leveraging processed data. Agents defined in `src.rl.agents` (RandomAgent, SkillMatchAgent, strategy-aware agents).
- Per-seed rollouts log to `reports/decomposition/rl_decomposition_metrics_seed_*.csv`; aggregated metrics (avg_reward, win_rate, starved_tasks, deadline_misses) stored in `reports/decomposition/rl_decomposition_metrics.csv`.
- Multi-agent variant via `run_multiagent.py` writes `rl_multiagent_metrics_seed_*.csv` + aggregate.

## Decomposition Benchmarking
- `make decomp_benchmark` runs `src.decomposition.runners.run_batch` over `experiments/decomposition/benchmark_tasks.json`.
- Strategy registry (`src.decomposition.registry.STRATEGIES`) enumerates Planner/Verifier variants (contract-first, pattern-skeleton, etc.).
- Outputs: `reports/decomposition/strategy_comparison.csv`, `cost_vs_quality.csv`, `ablation_by_task_type.csv`, summary markdown, etc.
- Additional runners: `run_meta_selector.py` (meta-policy tuning), `run_real_slice.py` (real tasks), `run_multiagent.py` (Planner + k Solver + Verifier workflow).

## Reporting + Paper Assets
- Existing paper scripts (e.g., `paper/main.tex`, `reports/decomposition/latex_tables.tex`).
- RL + decomposition evaluations feed `analysis/` notebooks and `expo_materials/` presentations.
- Upcoming work (per task requirements) will add final artifact compilation, Tower-of-Hanoi benchmark, regression targets, and end-to-end ablations built on top of these components.

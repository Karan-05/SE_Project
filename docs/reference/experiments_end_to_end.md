# experiments.end_to_end

_Summary_: End-to-end experiment orchestration + ablation reporting.

## Classes
### Resources
No class docstring.

## Functions
- `_load_json_or_yaml(path)` — 
- `_load_rl_metrics(report_dir, pattern, agent_col)` — 
- `_load_cost_tokens(report_dir)` — 
- `_load_embedding_ratio(tables_dir)` — 
- `_load_regression_r2(out_dir)` — 
- `bootstrap_ci(values, rng, iters)` — 
- `run_variant(variant_cfg, seed, resources)` — 
- `summarize_runs(df, rng)` — 
- `plot_ablation(summary, out_path)` — 
- `run_end_to_end(config_path, out_dir, num_seeds=, base_seed=, seed=)` —

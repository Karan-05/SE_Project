# decomposition.runners.run_meta_selector

_Summary_: Train a leakage-audited meta-selector that picks the best strategy per task.

## Functions
- `_load_tasks(tasks_file)` — 
- `_best_strategy_per_task(df)` — 
- `_row_features(task, row, label)` — 
- `build_dataset(tasks_file, comparison_file)` — 
- `_encode_features(df, feature_cols)` — 
- `_train_model(train_df)` — 
- `_task_level_split(dataset)` — 
- `train_meta_selector(dataset)` — 
- `predict_best_strategies(model, feature_cols, dataset)` — 
- `_write_audit(model, feature_cols, output_path)` — 
- `_run_loo_type(dataset, out_path)` — 
- `parse_args()` — 
- `main()` —

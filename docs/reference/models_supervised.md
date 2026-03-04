# models.supervised

_Summary_: Supervised learning baselines for competition outcomes and market dynamics.

## Classes
### DatasetBundle
No class docstring.

### SupervisedExperiment
Train and evaluate models across multiple targets and feature bundles.

Methods:
- `__init__(processed_dir, config, feature_mode)` — 
- `_read_table(name)` — 
- `_load_dataset()` — 
- `_maybe_merge_embeddings(df)` — 
- `_prepare_features()` — 
- `_build_column_transformer(df)` — 
- `_get_models(task_type)` — 
- `_split(df, target)` — 
- `_plot_feature_importance(pipeline, target, model_name)` — 
- `run()` — 

## Functions
- `run_ablation(feature_modes, processed_dir, config)` —

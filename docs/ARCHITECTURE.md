# Architecture & Code Tour

## How to Read This Repo
1. **Start with `docs/PIPELINE_MAP.md`** for the chronological flow from data ingest → supervised → RL → decomposition.
2. **Use this file** to understand how directories and modules map to that flow.
3. **Browse `docs/reference/_index.md`** (auto-generated via `python scripts/generate_module_docs.py`) for per-module summaries, docstrings, and callable signatures. Regenerate whenever code changes.
4. **See `docs/EVIDENCE.md`** for how experiments turn into paper-ready artifacts (CLI commands + outputs + claims).

## Directory-Level Overview

| Path | Role | Key Entrypoints |
| --- | --- | --- |
| `src/data/` | Preprocessing raw CSV/Parquet into canonical parquet + feature engineering. | `python -m src.data.preprocess` |
| `src/models/` | Embedding + supervised modeling pipelines feeding the predictor. | `train_supervised.py`, `train_embeddings.py` |
| `src/decomposition/` | Planner/Solver/Verifier strategies + registries + evaluation harnesses. | `python -m src.decomposition.runners.*` |
| `src/rl/` | Gymnasium env + agents for marketplace rollouts. | `python -m src.decomposition.runners.run_rl_integration` |
| `src/benchmarks/toh/` | Tower-of-Hanoi env + strategies + CLI benchmark. | `python -m src.benchmarks.toh.run` |
| `src/regression/` | Continuous-target dataset builder + regression runner. | `python -m src.regression.run_regression` |
| `src/experiments/` | End-to-end ablations + paper-worthy reporting. | `python -m src.experiments.run_end_to_end` |
| `src/final/` | Artifact compiler stitching supervised/RL/decomposition outputs. | `python -m src.final.compile_paper_artifacts` |
| `docs/reference/` | Auto-generated module reference (classes/functions/docstrings). | `make docs_reference` (or run script) |

## Execution Graph
1. **Data Ingest:** `make preprocess` → `src/data/preprocess.py` outputs `data/processed/*.parquet`.
2. **Supervised Models:** `train_supervised.py` consumes processed data + optional embeddings (`embeddings/`) and writes `reports/tables/supervised_metrics_*.csv`.
3. **RL + Decomposition:** Targets such as `make decomp_benchmark`, `make decomp_rl_seeds`, and `make decomp_multiagent` run under `src/decomposition/runners/` and emit CSVs in `reports/decomposition/`.
4. **Tower-of-Hanoi Benchmark:** `make toh_benchmark` uses `src/benchmarks/toh` to gather success/token curves for adaptive planning evidence.
5. **Regression Targets:** `make regression_eval` drives `src/regression/run_regression.py` to quantify submission/winning-score predictors.
6. **End-to-End Ablations:** `make end_to_end_eval` → `src/experiments/run_end_to_end` merges RL metrics, embeddings, regression R² to evaluate ablations (full / no_rl / no_multi_agent / predictor_only).
7. **Paper Artifact Compilation:** `make final_artifacts` → `src/final/compile_paper_artifacts` collates supervised, RL, frontier, and ablation tables/plots into `reports/final/`.
8. **One-Button Pack:** `make paper_artifacts` runs steps 4–7 sequentially and prints output locations.

## Navigating Modules
- Each module in `src/` has a dedicated Markdown page in `docs/reference/`. Example: `docs/reference/benchmarks_toh_run.md` documents the CLI runner, its functions (`run_episode`, `run_benchmark`, `parse_args`, `main`), and their docstrings.
- Use `_index.md` inside that folder as a table of contents; clicking a link opens the Markdown with class/method/function summaries.
- Regenerate whenever code changes: `./venv/bin/python scripts/generate_module_docs.py`

## Extending the Research
- **New strategy?** Register it in `src/decomposition/registry.py`, document it via docstrings so the reference script picks it up, add CLI mention here.
- **New experiment?** Add a CLI under `src/experiments/`, write metrics to `reports/<domain>/`, then update `docs/EVIDENCE.md` with command + outputs + claim.
- **Paper updates?** Use `docs/EVIDENCE.md` + `reports/final/` as your source of truth for tables/figures; the LaTeX snippets live there already.

Maintaining these docs (architecture overview + auto-generated module references + evidence guide) keeps the entire project explainable line-by-line for any future ChatGPT Research collaborator. Whenever features land, re-run the generator and append sections here describing new flows so the map stays current.

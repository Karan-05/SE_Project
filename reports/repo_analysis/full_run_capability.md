# Full-run Capability Audit

“Run the entire project” can mean several different entry points. This note captures the scope, dependencies, and status of each variant.

## 1. Full ETL & Database build

- **Goal** – Pull fresh Topcoder data, normalize the JSON, and populate the MySQL warehouse.  
- **Pipeline**  
  1. `fetch_functions.py` + `http_utils.request_with_retries` scrape `/v5/challenges`, `/resources`, `/submissions`, and `/members/<handle>/stats`.  
  2. `legacy_excel_loader.py` backfills gaps from `old_Challenges.xlsx`.  
  3. `scripts/export_real_tasks.py --challenge-dir challenge_data/... --output-dir data/raw` merges the windows into `data/raw/*.csv`.  
  4. `dbConnect.dbConnect` writes the rows into the tables defined by `schema_registry.py` and applies migrations.  
- **Status** – Ready, but requires valid API credentials (especially the bearer token for submissions) and access to the MySQL host declared in `config.py`. Without those secrets, submissions fall back to synthetic counts and the DB ingest cannot proceed.

## 2. Raw-task export + preprocess

- **Goal** – Materialize the ML/RL-ready parquet bundle.  
- **Pipeline**  
  1. Run `scripts/export_real_tasks.py` (or reuse the existing `data/raw/*.csv`).  
  2. Execute `python -m src.data.preprocess --raw-dir data/raw --output-dir data/processed`. This produces `tasks/workers/interactions/market` in both CSV and Parquet, plus `metadata.json`.  
  3. Optional: `python src/regression/build_dataset.py` to build the evaluation splits used by the regression baseline.  
- **Status** – Fully automated (no external credentials). The repo already ships with a populated `data/raw` directory, so `make preprocess` completes immediately.

## 3. Real-repo benchmark (Topcoder SRM repos)

- **Goal** – Run the repo harness + strategies on every SRM task snapshot under `experiments/real_repo_tasks/topcoder`.  
- **Pipeline**  
  1. `make real_repo_preflight` → calls `scripts/prepare_real_repo_benchmark.py --prep-only` to validate LLM credentials, confirm repo snapshots, and capture preflight reports.  
  2. `make real_repo_run` → same script without `--prep-only`, which invokes `run_real_repo_benchmark` (strategies, oracle teacher, CGCS instrumentation).  
  3. Outputs go to `reports/decomposition/real_world/real_repo`. Traces land in `reports/decomposition/traces/<strategy>`.  
- **Dependencies** – Requires an OpenAI (or compatible) provider configured via `src/providers/llm`. The harness assumes node/npm for the Topcoder repos; missing runtimes will be flagged during preflight.  
- **Status** – Ready as soon as provider credentials and repo snapshots exist; the repo already contains sample runs for the API backlog tasks.

## 4. Topcoder funnel (index → executable subset → diagnostics)

- **Goal** – Audit the full 22k corpus, isolate runnable repos, and emit counts for every funnel stage.  
- **Pipeline**  
  1. `python scripts/topcoder/build_corpus_index.py --tasks data/raw/tasks.csv` → `data/topcoder/corpus_index.jsonl` + `corpus_summary.json` (current summary: `indexed_rows=22,023`, `repo_count=16,568`, `duplicate_group_count=2,060`).  
  2. `python scripts/topcoder/select_executable_subset.py --input data/topcoder/corpus_index.jsonl` → `data/topcoder/executable_subset.jsonl` with rejection reasons (`selected_rows=3,966`, `missing_test_signal=6,652`, `duplicate=10,585`).  
  3. `python scripts/topcoder/build_funnel_report.py` → `data/topcoder/funnel_report.json` + `reports/ase2026_aegis/funnel_snapshot.md`, summarising raw corpus, subset, CGCS rows (60), eval items (9), and batch outputs (0 so far).  
- **Status** – Fully scripted and credential-free; all outputs checked into the repo. These scripts now make it obvious which challenges are indexed, likely executable, runnable, or still empty in CGCS.

## 5. Source acquisition & repo recovery

- **Goal** – Materialize the artifact candidate inventory, clone/download real repos at scale, and capture audit trails for both successes and rejections.  
- **Pipeline**
  1. `make topcoder_discover_artifacts` → runs `scripts/topcoder/discover_repo_candidates.py` to emit `data/topcoder/artifact_candidates.jsonl` + `artifact_candidates_summary.json` and the filtered `data/topcoder/repo_candidates.jsonl`. Every URL is typed (`git_repo`, `api_endpoint`, `web_app`, `docs_page`, etc.) with acquisition strategies and confidence scores.  
  2. `make topcoder_fetch_repos` → wraps `scripts/topcoder/fetch_topcoder_repos.py`. Use `--recovery-mode high-recall --allowed-hosts github.com,gitlab.com,bitbucket.org --reject-host-patterns execute-api,amazonaws.com,cloudfront.net --prefer-archive-fallback --skip-non-source --emit-rejections` to validate git remotes via `git ls-remote`, shallow-clone real repos, download archives when necessary, and log every rejection reason to `data/topcoder/repo_fetch_manifest.jsonl`.  
  3. `make topcoder_build_snapshots` + `make topcoder_prepare_workspaces` propagate `source_origin`/`source_url`/`archive_hash` into `data/topcoder/repo_snapshots.jsonl` and `data/topcoder/workspace_manifest.jsonl` so downstream runners know which repos are clones vs. archive extractions vs. synthetic stubs.  
  4. `make topcoder_source_report` consolidates metrics from every stage into `data/topcoder/source_acquisition_report.json` + `reports/ase2026_aegis/source_acquisition_snapshot.md`.  
  5. `make topcoder_debug_repo_recovery` (`scripts/topcoder/debug_repo_recovery.py`) summarizes host distributions, rejection reasons, clone/archive success rates, and sample false positives in `data/topcoder/repo_recovery_debug.json` + `reports/ase2026_aegis/repo_recovery_debug.md`.  
- **Status** – Fully scripted and credential-free. Network access is only needed for the clone/download stage; dry-run mode records what would happen without touching the network.

## 6. RL / universal-agent runs

- **Goal** – Train or evaluate the STRIDE/AeGIS/TARL stacks on the synthetic market.  
- **Pipeline**  
  1. Training: `make run_rl` (single seed) or `make decomp_rl_seeds` (full sweep).  
  2. Evaluation: `make decomp_real` (real-slice replay), `make decomp_frontier` (frontier curves), `scripts/run_aegis_suite.py` (full AeGIS sweep).  
  3. Results live under `results/aegis_rl/` and `reports/ase2026_aegis`.  
- **Dependencies** – No external credentials; uses the `processed/*.parquet` bundle. GPU acceleration optional.

## 7. CGCS dataset + paper assets

- **Goal** – Publish the clause-level dataset and update the paper figures.  
- **Pipeline**  
  1. `make cgcs_dataset` to build `data/cgcs/{train,dev,test}.jsonl`.  
  2. `python scripts/anonymize_artifact.py --source data/cgcs --dest artifacts/cgcs_anonymized` for artifact submission.  
  3. `make paper_tables` and `make paper_figures` to regenerate the CGCS contributions inside `reports/ase2026_aegis`.  
- **Status** – Ready; depends only on existing run logs in `reports/decomposition/real_world/real_repo`. Current strict run yields 60 rows (all rejected), so improvements require richer traces or relaxed filters.

### Summary

- **Credentialed runs** – Only the API fetch (bearer token) and real-repo benchmark (LLM provider + repo snapshots) require secrets.  
- **Data-only runs** – Preprocess, RL training, dataset builds are fully scripted and reproducible from the committed assets.

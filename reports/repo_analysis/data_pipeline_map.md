# Topcoder Data Pipeline Map

This map traces the full chain from the live Topcoder feeds to CGCS-ready experiments and cites the code that implements each hop.

## 1. Acquisition & API Backfill

- **CLI + automation** – `init.py` validates user-provided windows/tracks/status and boots `setUp.setUp.request_info` to hit the `/v5/challenges` API with retries before downloading (`setUp.py` lines 14‑123, 67‑119). `automation.Automation.fetch_challenges` stitches these windows for an entire year and immediately launches ingestion for every month (`automation.py` lines 24‑99).  
- **HTTP plumbing** – `fetch_functions.py` centralizes API access. `get_data` streams paginated challenge windows (`lines 34‑110`), `fetch_challenge_registrants`/`fetch_challenge_submissions`/`fetch_member_data`/`fetch_member_skills` enrich registrant, submission, and profile tables (`lines 113‑214`). All requests reuse the shared retry helper in `http_utils.request_with_retries`.  
- **Outputs** – Every payload is normalized through `process.format_challenge` before being written to `challenge_data/challengeData_<start>_<end>/pageN.json`, ensuring the downstream tooling sees consistent schemas regardless of fetch date.

## 2. Legacy Excel & Historical Backfill

- `legacy_excel_loader.convert_excel_to_json` ingests `old_Challenges.xlsx`, cleans every cell through `process.format_legacy_excel_row`, and emits `challenge_data/challengeData_<window>/*.json` that mirror the API downloads. The loader prefers pandas but falls back to a manual XML reader so historical `.xlsx` archives can always be converted (see `legacy_excel_loader.py` lines 16‑199).

## 3. JSON Normalization & Raw Task Export

- `process.py` houses the canonical formatters for challenges/members/skills. This is where prize totals are derived (`calculate_prizes`), timestamps are coerced to ISO strings, winners and tags are flattened, and Excel serial numbers are converted to MySQL-compatible datetimes.  
- `scripts/export_real_tasks.export_real_tables` walks every `challenge_data/challengeData_*` directory (`_iter_challenge_payloads`), deduplicates by `challengeId`, and emits `data/raw/{tasks,workers,interactions}.csv`. Registrant/submission timelines are synthesized deterministically when the bearer token is absent so the exported bundle is reproducible without credentials.

## 4. MySQL Schema, Loading, and Snapshots

- `schema_registry.TableRegistry` defines the authoritative schema for Challenges, Members, and Challenge_Member_Mapping, including insert/upsert clauses.  
- `dbConnect.dbConnect` wires credentials (`config.load_db_config`), creates the database, applies pending migrations via `migrations.MigrationRunner`, and exposes helpers for member deduplication (`check_member`) plus Excel exports (`excel_uploader`).  
- `uploader.Uploader` is the ingestion workhorse: it scans each JSON window, inserts/upserts challenges, pulls registrants/submissions via `fetch_functions`, records mapping rows, maintains a TTL-based member cache (`check_unique_members`), and finally loads member profiles/skills. The resulting tables mirror the `data/raw` CSV bundle and act as the ground-truth warehouse.

## 5. Export → Preprocess → Parquet

- The repo ships `data/raw/*.csv`, but `scripts/unpack_large_assets.py` can rebuild them from the versioned `.gz` assets when needed.  
- `src/data/load.load_or_generate` reads these exports (synthesizing fallback data only when the bundle is missing).  
- `src/data/preprocess.preprocess` materializes ML/RL-ready tables: datetimes are parsed, derived metrics like `duration_days`, `market_bucket`, `local_time_load`, worker embeddings, and interaction flags are added, and both CSV + Parquet copies land in `data/processed`. Each run also records `metadata.json` with the `DataConfig` used for reproducibility.

## 6. Corpus, Funnel, and Source Acquisition

- `scripts/topcoder/build_corpus_index.py` merges `data/raw/tasks.csv` with every JSON window, annotates repo/test/code signals, generates duplicate keys, and writes `data/topcoder/{corpus_index.jsonl,corpus_summary.json}` — the latter confirms 22 023 indexed rows, 16 568 repo hits, and 2 060 duplicate clusters in this repo.  
- `scripts/topcoder/select_executable_subset.py` enforces runnable filters (repo, tests, ≥1 submission, Dev/QA tracks, dedupe) and emits `data/topcoder/executable_subset.jsonl` + `executable_subset_summary.json` (3 966 retained rows, rejection reasons logged per challenge).  
- `scripts/topcoder/discover_repo_candidates.py` scans every description/tag for URLs, classifies them via `src/decomposition/topcoder/discovery`, and produces `artifact_candidates.jsonl` (typed URLs + acquisition strategy) plus `repo_candidates.jsonl` (clone/download attempts).  
- `scripts/topcoder/fetch_topcoder_repos.py`, `build_repo_snapshots.py`, and `prepare_workspaces.py` capture clone/archive outcomes (`repo_fetch_manifest.jsonl`), promote them to normalized snapshots/workspaces, and roll up metrics via `build_repo_acquisition_report.py`. Diagnostics live in `scripts/topcoder/debug_repo_recovery.py`.  
- `scripts/topcoder/build_funnel_report.py` fuses raw corpus counts, executable subset, CGCS slices, eval packs, and OpenAI batch metadata into `data/topcoder/funnel_report.json` + `reports/ase2026_aegis/funnel_snapshot.md`.

## 7. Decomposition, RL, and Universal-Agent Experiments

- **Workflow RL** – `src/rl/workflow_env.py` and `src/rl/workflow_agents.py` implement the Gymnasium environment plus baselines. Higher-level stacks (AEGIS, STRIDE, TARL, counterfactual STRIDE) live under `src/rl/aegis_*`, `src/rl/stride_*`, and `src/rl/cstride_value.py`. Entry points include `experiments/run_aegis_rl.py`, `experiments/run_stride_aegis.py`, and automation helpers (`scripts/run_stride_suite.py`, `scripts/run_tarl_suite.py`, `scripts/run_cstride_aegis.py`). All results land in `results/aegis_rl/**` and are summarized into `reports/ase2026_aegis/*.csv`.  
- **Decomposition & CGCS** – `scripts/prepare_real_repo_benchmark.py` orchestrates real Topcoder SRM repos using the harness under `src/decomposition/real_repo/*` (loader, preflight, witnesses, contract graph). Plan execution lives in `src/decomposition/agentic/loop.py`, while strategy implementations sit in `src/decomposition/strategies/*`. Completed traces populate `reports/decomposition/**` and feed the CGCS dataset builder.  
- **Universal-agent sampling** – `src/decomposition/runners/run_batch.py` and `run_real_slice.py` replay tasks drawn from `data/processed/tasks.parquet` or the executable subset, letting LLM agents operate outside the repo harness with the same instrumentation.

## 8. CGCS Dataset & Paper Assets

- `scripts/build_cgcs_dataset.py` converts real-repo traces into `data/cgcs/{train,dev,test}.jsonl`, capturing clause IDs, witnesses, override signals, and failure categories. `scripts/anonymize_artifact.py` prepares the public-safe artifact bundle.  
- `scripts/make_paper_tables.py`, `scripts/make_paper_figures.py`, and the STRIDE/AEGIS table/figure helpers regenerate all ASE-ready artifacts in `reports/ase2026_aegis`. Supporting docs (`docs/CGCS_DATASET_SCHEMA.md`, `docs/REPRODUCIBILITY.md`, `reports/ase2026_aegis/*`) plus the per-session log keep the provenance of every run auditable.

Together these stages form an unbroken, reproducible chain: API/Excel → normalized JSON → MySQL + CSV → processed Parquet → corpus/funnel audits → repo acquisition → RL + decomposition experiments → CGCS dataset + paper-ready assets.

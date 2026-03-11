# Executable Task Audit

## 1. Sources inspected
- **Topcoder corpus** – `challenge_data/challengeData_*/*.json`, `data/raw/{tasks,workers,interactions}.csv`, and `data/processed/tasks.*` contribute 22,023 metadata-only challenges (see `analysis/output/challenges_summary.csv` and `reports/repo_analysis/topcoder_dataset_audit.md`). No repositories, starter code, or tests ship with these rows.
- **Synthetic benchmark tasks** – `experiments/decomposition/benchmark_tasks.json` lists 50 algorithmic problems with curated I/O tests and reference solutions. Every decomposition run (`make decomp_benchmark`, `arch_template_*`, `topcoder_*`) loads this file when it needs ground-truth coding tasks.
- **Self-verifying experiment runs** – `reports/experiments/*/per_problem.csv` captures each invocation of `tools/run_topcoder_experiment.py`. Large runs include:
  - `topcoder_full_run` (852 dataset rows, 281 unique task IDs) derived from `challenge_data`, `data/raw`, and `data/processed`.
  - `topcoder_20260223_123724` (66,712 dataset rows, 22,115 unique task IDs) that sweeps almost the entire corpus plus `analysis/output` task tables.
  - Architecture/doc sweeps under `arch_template_check` (100 tasks) and `arch_template_arch_only` (15 tasks).
  - Presentation demos `topcoder_present_demo*` that sample `analysis/output/ai_*` CSVs.
- **Presentation/analysis manifests** – `analysis/output/ai_feasibility_analysis.csv` and `analysis/output/ai_super_analysis.csv` feed “presentation” style tasks with no runnable assets.

Every dataset/run pair is catalogued in `reports/repo_analysis/task_dataset_manifest_full.csv` (129 entries) and the run-level metrics sit in `reports/repo_analysis/experiment_run_summary.csv`.

## 2. Category summary
Using the manifest (`task_dataset_manifest_full.csv`), each dataset/run pair was classified by the kind of validation it actually supports:

| Category | Description | Tasks (run-level) | Notes |
| --- | --- | --- | --- |
| executable coding task with runnable tests | 50 benchmark problems reused across runs (160 run-level rows) with curated tests under `experiments/decomposition/benchmark_tasks.json` | 160 | Only truly repeatable coding problems discovered. |
| coding task with partial validation only | 39 unique Topcoder-derived tasks in `topcoder_full_run` (36 synthetic, 3 statement) plus a handful of duplicates in other runs | 876 | Tests are LLM-synthesised or scraped from statements; no linked repositories. |
| architecture/doc task | 115 architecture or rubric-only deliverables from `arch_template_*` runs | 7 (dataset/run rows) | Verified via rubric scores; no executable artefacts. |
| data/ETL spec task | 35–113 deliverables labelled `data_etl` that expect textual ETL plans | 113 | Entirely rubric-based. |
| coding task (no runnable assets) | 71 repo-patch/API tasks in `arch_template_check` that need repositories the repo does not ship | 71 | Classified separately so we know they cannot run locally. |
| presentation/analysis task | 65,893 rows sampled from `analysis/output` AI feasibility/super-analysis tables | 65,893 | Informational/planning requests; no code. |
| metadata-only Topcoder challenge | The remaining 982 run-level rows (plus 22,023 corpus entries) that were skipped because no coding spec/tests exist | 982 | Includes all `skipped_non_coding_task` rows in `topcoder_full_run` and the full-corpus sweep. |

## 3. Executable subset (ground truth)
- **Canon** – `experiments/decomposition/benchmark_tasks.json` (50 tasks, see also `reports/experiments/benchmark_subset/tasks_manifest.json`). `reports/experiments/topcoder_full_run/per_problem.csv` confirms 50 successes out of 50 with `tests_source="provided"`.
- **Assets** – Task metadata (`problem_statement`, `reference_solution`, `tests`) lives inline inside the JSON, and every strategy run caches executions in `artifacts/self_verifying/benchmark_subset/*`.
- **Manifests** – These rows appear with `category_code=executable_coding_curated_tests` inside `reports/repo_analysis/executable_subset_manifest.csv`. Filtering on that category reveals nine dataset/run pairs, all pointing back to the same 50 tasks.
- **Run instructions** – `make decomp_benchmark` or `python src/decomposition/runners/run_batch.py --benchmark experiments/decomposition/benchmark_tasks.json` reproduces the results with deterministic tests.

**Size** – 50 unique tasks; the repo currently has no other fully-instrumented programming problems.

## 4. Partial-validation coding tasks
- **Coverage** – `reports/repo_analysis/_topcoder_full_run_task_summary.csv` shows 36 tasks with synthetic tests and 3 tasks with statement-parsed tests (task IDs `181e5a18-8f46-4366-9aa7-4550a25adceb`, `355a5497-71c3-4e3a-b200-f53d62564667`, `91e34246-16b8-417d-8eb6-f7dc38c9b320`). The generated test specs live under `reports/experiments/topcoder_full_run/generated_tests/*.json`.
- **Quality** – These tests invent hypothetical Python call signatures (example: `generated_tests/051e70ad-a32b-40fc-86c8-fe55b67fd611.json` expects `fetch_scorecard_details` and `create_appeal` helpers even though no repository ships them). They ensure decomposition strategies have something to execute, but there is no linkage to real challenge repositories.
- **Manifest entries** – All dataset/run rows flagged as `coding task with partial validation only` inside `executable_subset_manifest.csv`. Each row lists how many tests came from statements vs synthesis so we can triage the most promising subset (e.g., `topcoder_full_run` rows with `tests_source_statement=1`).
- **Execution gap** – Because these tasks stand on synthetic scaffolding, success merely means “LLM code satisfied fabricated tests”, not that it solved an actual Topcoder repository.

**Size (upper bound)** – 39 unique tasks appear with any tests in `topcoder_full_run`; other runs only reuse that set. Treat them as pilot candidates until we backfill genuine repositories/tests.

## 5. Non-executable task families
- **Architecture/documentation** – `arch_template_check/per_problem.csv` (100 rows) and `arch_template_arch_only/per_problem.csv` (15 rows) route tasks to rubric verifiers (`rubric_architecture_doc`, `rubric_data_etl`, `rubric_repo_patch`). All 115 rows lack tests (`tests_provided=False` in the CSV). They fall under `architecture/doc task` or `data/ETL spec task` inside `non_executable_subset_manifest.csv`.
- **Repository patch/API work** – The same `arch_template_check` run labelled 16 tasks as `repo_patch`/`api_backend`, but the repo does not ship any scaffolding repositories or build scripts. These rows are categorised as `coding task (no runnable assets)` so we know they need external repos before evaluation.
- **Presentation/analysis-only requests** – Runs such as `topcoder_20260223_123724` and `topcoder_present_demo` ingest `analysis/output/ai_feasibility_analysis.csv` and `analysis/output/ai_super_analysis.csv`. They ask for slide decks, opportunity assessments, or AI-planning documents. `per_problem.csv` for the big sweep (66,712 rows) reports `tests_provided=False` everywhere and `status=skipped_missing_tests` for all “presentation” keywords.
- **Metadata-only challenges** – In both `topcoder_full_run` and the full-corpus sweep, 20k+ tasks were skipped immediately with `status=skipped_non_coding_task` because `task_router` could not find coding specs/test hooks inside the challenge descriptions.

## 6. Manifest files
- `reports/repo_analysis/executable_subset_manifest.csv` – dataset/run rows that expose any tests (columns include run_id, dataset_id, task counts, per-test-source counts, and category labels). Use this to pick the best candidate sets for the new evaluation harness.
- `reports/repo_analysis/non_executable_subset_manifest.csv` – dataset/run rows that currently have no runnable assets, grouped by architecture/doc, presentation, repo patch, data/ETL, or metadata-only tasks.
- `reports/repo_analysis/task_dataset_manifest_full.csv` – superset manifest if we need to reclassify categories later.
- `reports/repo_analysis/experiment_run_summary.csv` – high-level stats per `reports/experiments/<run_id>` folder (rows processed, unique task IDs, number of rows that ever exposed tests).

## 7. Key takeaways
1. Only 50 benchmark tasks have trustworthy runnable tests today.
2. A further ~40 tasks rely on synthetic or statement-derived tests; they can exercise the decomposition loop but do not verify against real Topcoder repositories.
3. All remaining tasks (22k+ challenges, presentation/architecture specs, repo patches) lack reproducible artefacts; we must treat them as non-executable until we attach repositories/tests or human rubrics.
4. The new real-evaluation harness should start with the 50 curated tasks and a carefully vetted subset of the 39 partially validated tasks, then deliberately expand coverage by sourcing real repositories/tests for priority challenges.

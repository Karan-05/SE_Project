# Session Log – 2026-03-10 (Real-repo prompt tuning + reporting refresh)

## Commands Run
1. `source venv/bin/activate && pwd`
2. `source venv/bin/activate && which python`
3. `source venv/bin/activate && python --version`
4. `source venv/bin/activate && cat reports/decomposition/real_world/real_repo/case_studies.md`
5. `source venv/bin/activate && sed -n '1,200p' src/decomposition/agentic/solver.py` (plus matching inspections for `loop.py`, `executor.py`, `real_repo/harness.py`, `run_real_repo_benchmark.py`, and the Topcoder task folders)
6. `source venv/bin/activate && PYTHONPATH=. python scripts/run_prompt_tuning_iteration.py --mode real_world_research --strategies contract_first,failure_mode_first --task-root experiments/real_repo_tasks/topcoder --label semantic_multi_file --notes "...` (failed preflight because provider=model=`mock`)
7. `source venv/bin/activate && PYTHONPATH=. python scripts/run_prompt_tuning_iteration.py --mode dev --reports-mode real_world_research --strategies contract_first,failure_mode_first --task-root experiments/real_repo_tasks/topcoder --require-reportable --exclude-fixtures --label semantic_multi_file --notes "Improved multi-file prompting and oracle validation."`
8. `source venv/bin/activate && npm ci --no-audit --no-fund` (inside `experiments/real_repos/tc-template-node-postgres`, to validate test behaviour outside the harness)
9. `source venv/bin/activate && npm test -- --reporter dot test/problems.list.spec.js || true` (confirming the clean repo still fails metadata/tag tests, i.e., the ground-truth patch is required)

## Files Modified / Created
- Repo tasks: captured repo snapshot hash inside `experiments/real_repo_tasks/topcoder/a160ded4_*/*.json` (all four SRM tasks now record `repo_snapshot_sha256`).
- Agentic loop & prompts: `src/decomposition/agentic/{solver.py,loop.py,executor.py,traces.py}` gained multi-file guidance, repair diagnosis summaries, attempt-level metrics, and ExecutionResult plumbing.
- Harness/runners: `src/decomposition/real_repo/{loader.py,harness.py}` now compute snapshot fingerprints, log teacher patch attempts, and expose context snippets; `src/decomposition/runners/run_real_repo_benchmark.py` gained richer reporting + prompt-tuning hooks; new workflow script `scripts/run_prompt_tuning_iteration.py`.
- Reports: regenerated `reports/decomposition/real_world/real_repo/{strategy_comparison.csv,summary.md,case_studies.md,preflight_report.*}` plus three prompt-tuning iteration folders under `reports/decomposition/real_world/real_repo/prompt_tuning/`. Updated `reports/repo_analysis/{data_pipeline_map.md,full_run_capability.md}` and `reports/ase2026_aegis/{main_method_decision.md,paper_positioning.md,abstract_draft.md,contributions_draft.md,session_log.md}` to reflect the new evidence.

## Metrics Observed
- Real-repo benchmark (compatibility mode): contract_first & failure_mode_first both 0.00 pass_rate, localization precision 1.00, localization recall 0.08, target recall 0.75, multi-file edit rate 0.00, multi-file attempt rate 0.00, under-localized-ground-truth rate 1.00 (`reports/decomposition/real_world/real_repo/summary.md`).
- Oracle_teacher rows still `patch_failed` because Topcoder’s `ground_truth.patch` files omit hunk metadata (`ground_truth_teacher_patch.log` captures the “I can’t seem to find a patch” error), but snapshot verification now proves repo copies match the expected SHA256.
- Prompt-tuning summary (`reports/decomposition/real_world/real_repo/prompt_tuning/20260310-121954_semantic_multi_file/iteration_summary.md`) matches the above metrics and logs deltas vs. prior iterations.
- Direct `npm test` run on the clean `tc-template-node-postgres` repo fails six SRM tests with `ReferenceError: includeComponents is not defined`, confirming the harness patches are necessary for solvability even though they cannot be auto-applied here.

## Blockers / Risks
- This sandbox exposes only the mock provider/model, so preflight forbids `--mode real_world_research`. All benchmark data therefore comes from compatibility runs (`--mode dev --reports-mode real_world_research`), which copy the real repo and run builds/tests but still use mock completions.
- Topcoder’s published `ground_truth.patch` files lack unified hunk metadata and include `*** Add File` sections, so the POSIX `patch` CLI cannot apply them. We now log the failure reason, but the oracle rows cannot demonstrate passing tests until the patch format is upgraded or an alternate source of ground-truth files is provided.

## Next Steps
1. Replace `ground_truth.patch` with standard unified diffs (or add a parser that understands the current minimal format) so the teacher baseline can actually apply patches and produce passing rows.
2. Obtain a non-mock LLM provider (OpenAI key, Anthropic, or local Ollama) so we can re-run `scripts/run_prompt_tuning_iteration.py --mode real_world_research` without compatibility flags.
3. Extend the prompt-tuning workflow to cover additional repos/tasks once new snapshots + tests are staged, and feed the resulting multi-file metrics directly into the ASE paper figures.

---

# Session Log – 2026-03-11 (Contract-aware semantic ablations)

## Commands Run
1. `python -m json.tool experiments/real_repo_tasks/topcoder/a160ded4_*/task.json` (contract metadata sanity check)
2. `OPENAI_API_KEY=… LLM_PROVIDER=openai LLM_MODEL=gpt-4.1-mini python -m src.decomposition.runners.run_real_repo_benchmark --mode real_world_research --strategies contract_first,contract_first_baseline,contract_first_checklist,failure_mode_first,failure_mode_first_baseline`

## Files Modified / Created
- Enriched every Topcoder task manifest with explicit `contract` entries, schema hints, and edit-policy breakdowns (`experiments/real_repo_tasks/topcoder/a160ded4_*`).
- Added semantic variant plumbing plus contract-aware prompts, checklists, repair critics, and contract-coverage metrics (`src/decomposition/agentic/{loop.py,semantic.py,solver.py}`, `src/decomposition/real_repo/{contracts.py,harness.py}`).
- Registered new ablation strategies (`contract_first_baseline`, `contract_first_checklist`, `failure_mode_first_baseline`) in `src/decomposition/strategies/*` and `registry.py`.
- Updated the reporting stack to surface contract coverage, semantic failure categories, and case-study details (`run_real_repo_benchmark.py`, `reports/decomposition/real_world/real_repo/*`).
- Refreshed ASE notes (`reports/ase2026_aegis/{main_method_decision.md,paper_positioning.md,abstract_draft.md,contributions_draft.md,session_log.md}`) to state that localization is solved and semantics remain the bottleneck.

## Metrics Observed
- Oracle_teacher still passes all 4 SRM tasks (pass_rate=1.0).
- Learned variants now report localization precision=1.0 and implementation recall=1.0 across the board, but contract coverage ranges from 0.38 (baseline) to 0.67 (checklist/full), confirming that the remaining failures are semantic (categories: aggregation/filtering/architecture). No learned strategy passed yet, but the failure reports now read “missing metadata totals,” “tag filter incomplete,” etc., instead of vague “tests_0.”

## Blockers / Risks
- `.git` remains read-only, so the new code cannot be committed/pushed until filesystem permissions are restored. All modified paths are ready to stage once writing to `.git` is allowed.

## Next Steps
1. Explore higher-capacity repairs (longer budgets or retrieval snippets) now that contract coverage is tracked per attempt.
2. Investigate whether mixing controller + service edits (even though the oracle doesn’t need them here) helps satisfy remaining metadata contracts.
3. Once git permissions return, commit/push these semantic upgrades so future runs and reviewers can reproduce the ablation study.

---
# Session Log – 2026-03-07 (Legacy export + reporting refresh)

## Commands Run
1. `python legacy_excel_loader.py old_Challenges.xlsx --output-dir challenge_data --window-name legacy_xlsx --output-file page1.json`
2. `python analysis/report.py --challenge-dir challenge_data --member-mapping snapshots/Challenge_Member_Mapping.csv --output-dir analysis/output`
3. `python scripts/export_real_tasks.py --challenge-dir challenge_data --output-dir data/raw`
4. `python -m src.data.preprocess --raw-dir data/raw --output-dir data/processed`

## Files Modified / Created
- Regenerated `challenge_data/challengeData_legacy_xlsx/page1.json` plus refreshed `analysis/output/*`, `data/raw/*.csv`, and `data/processed/*`.
- Authored repo-analysis notes (`reports/repo_analysis/data_pipeline_map.md`, `reports/repo_analysis/topcoder_dataset_audit.md`, `reports/repo_analysis/full_run_capability.md`) and ASE drafts (`reports/ase2026_aegis/main_method_decision.md`, `paper_positioning.md`, `abstract_draft.md`, `contributions_draft.md`).

## Metrics Observed
- `analysis/output/challenges_summary.csv` → 22,023 unique rows (21,819 legacy Excel + 204 API windows) with $26.5M prize pool.
- `data/processed/metadata.json` → 22,023 tasks, 402,280 workers, 425,704 interactions.

## Blockers / Risks
- No MySQL credentials or `TOPCODER_BEARER_TOKEN`, so submission/member refresh remained snapshot-only.
- STRIDE override dataset tiny (~635 labelled steps), limiting model exploration.

## Next Steps
1. Provision MySQL + credentials and rerun `automation.py` annually.
2. Obtain bearer token for submissions/artifacts.
3. Expand STRIDE/TARL disagreement logging across more seeds/episodes.

---

# Session Log – 2026-03-09 (Real-repo benchmark upgrade)

## Commands Run
1. `python -m src.decomposition.runners.run_real_repo_benchmark --task-root experiments/real_repo_tasks/dev --strategies direct_baseline --max-tasks 1 --mode dev`
2. `git status -sb` (verification before summary)

## Files Modified / Created
- Multi-file harness + metrics: `src/decomposition/real_repo/harness.py`, `src/decomposition/agentic/{executor.py,loop.py,solver.py,traces.py}`.
- Repo task plumbing: `src/decomposition/real_repo/{task.py,loader.py,retrieval.py}`, `src/decomposition/runners/run_real_repo_benchmark.py`, new manifest folder `experiments/real_repo_tasks/dev/`.
- Reporting/docs: `reports/decomposition/development/real_repo/{strategy_comparison.csv,summary.md,case_studies.md,runs/**}`, `reports/decomposition/{development,real_world}/README.md`, `reports/decomposition/real_repo_developer_note.md`, `reports/repo_analysis/{data_pipeline_map.md,full_run_capability.md}`, `scripts/ingest_repo_tasks.py`.

## Metrics Observed
- Dev smoke run (`dev_repo_array_sum`, direct_baseline) logged in `reports/decomposition/development/real_repo/strategy_comparison.csv`. Localization precision=1.0, recall=0.5, timeout_rate=0, regen rate=1.0 (no localization attempts on the fixture).
- Candidate retrieval surfaced `["calculator/task.py", "calculator/__init__.py"]` and the harness recorded identical edits/proposals across repair rounds.

## Blockers / Risks
- No real Topcoder repository snapshots yet, so `--mode real_world_research` cannot run end-to-end until repos/tests are onboarded.
- Provider defaults to `mock` inside this sandbox; the runner now enforces non-mock providers for real-world runs, so we cannot produce publishable metrics here.

## Next Steps
1. Use `scripts/ingest_repo_tasks.py` + `data/raw/tasks.csv` to convert any available Topcoder repo snapshots into `experiments/real_repo_tasks/topcoder/`.
2. Run `python -m src.decomposition.runners.run_real_repo_benchmark --mode real_world_research ...` once real repos + non-mock providers are configurable to populate `reports/decomposition/real_world/real_repo/`.
3. Extend the retrieval heuristics (e.g., content-based grep) once larger repos highlight precision/recall limitations.

---

# Session Log – 2026-03-07 (STRIDE rerun)

## Commands Run
1. `source venv/bin/activate && pwd`
2. `source venv/bin/activate && which python`
3. `source venv/bin/activate && python --version`
4. `source venv/bin/activate && python -c 'import sys; print(sys.executable)'`
5. `source venv/bin/activate && sed -n '1,200p' experiments/run_stride_aegis.py`
6. `source venv/bin/activate && python experiments/run_stride_aegis.py --variant stride_without_uncertainty_features --episodes 32 --seeds 0 1 2 3 4 --notes "2026-03-07 rerun"` (failed until `PYTHONPATH=.`)
7. `source venv/bin/activate && PYTHONPATH=. python experiments/run_stride_aegis.py --variant stride_without_uncertainty_features --episodes 32 --seeds 0 1 2 3 4 --notes "2026-03-07 rerun"`
8. `source venv/bin/activate && PYTHONPATH=. python experiments/run_stride_aegis.py --variant stride_gate_plus_residual --episodes 32 --seeds 0 1 2 3 4 --notes "2026-03-07 rerun"`
9. `tail -n +1 results/aegis_rl/stride_variant_summary.csv`
10. `cat results/aegis_rl/stride_without_uncertainty_features_summary.json`
11. `cat results/aegis_rl/stride_gate_plus_residual_summary.json`
12. `cp results/aegis_rl/stride_metrics.csv results/aegis_rl/metrics_stride_without_uncertainty_features.csv`
13. `cp results/aegis_rl/stride_metrics.csv results/aegis_rl/metrics_stride_gate_plus_residual.csv`
14. `python - <<'PY' ...` (merged per-variant metrics)
15. `python scripts/make_stride_tables.py`
16. `cat reports/ase2026_aegis/stride_table_ablation.csv`
17. `rg -n "100%" reports/ase2026_aegis`
18. `sed -n '1,80p' reports/ase2026_aegis/{main_method_decision.md,paper_positioning.md,abstract_draft.md,contributions_draft.md}`

## Files Modified / Created
- `results/aegis_rl/stride_without_uncertainty_features_summary.json`, `stride_gate_plus_residual_summary.json`, consolidated metrics files, and regenerated STRIDE figures/tables (`reports/ase2026_aegis/stride_*`).

## Metrics Observed
- Teacher-only STRIDE: success 0.9875, override 0.0, avg cost 0.276.
- Residual STRIDE: success 0.7125 with override regret > win rate; TARL unchanged at 0 overrides / 0.98 success.

## Blockers / Risks
- No DB/bearer token; STRIDE dataset still imbalanced and scripts required manual `PYTHONPATH`.

## Next Steps
1. Automate STRIDE/TARL runners (avoid manual `PYTHONPATH` juggling).
2. Build richer disagreement logs before new override attempts.
3. Pursue DB rebuild + bearer token for end-to-end verification.

---

# Session Log – 2026-03-08 (Automation + dataset expansion)

## Commands Run
1. `python scripts/run_stride_suite.py --dataset-episodes 512 --notes "automated suite"`
2. `python scripts/run_stride_suite.py --dataset-episodes 512 --notes "automated suite (expanded dataset)" --rebuild-dataset`
3. `python scripts/run_stride_suite.py --dataset-episodes 2048 --notes "automated suite (expanded dataset)" --rebuild-dataset`
4. `cat results/aegis_rl/datasets/stride_dataset_summary.json`
5. `cat reports/ase2026_aegis/stride_table_{main,ablation}.csv`
6. `sed -n '1,80p' reports/ase2026_aegis/{main_method_decision.md,paper_positioning.md,abstract_draft.md}`
7. `docker compose -f docker-compose.mysql.yml up -d` (CLI rejected the short flag)
8. `docker-compose -f docker-compose.mysql.yml up -d` (permission denied – no access to `/Users/karanallagh/.colima/default/docker.sock`)

## Files Modified / Created
- Added `scripts/run_stride_suite.py` (initial version) and updated documentation/figures accordingly.

## Metrics Observed
- Disagreement dataset grew to 19,542 labelled steps (3,372 positive overrides).
- Teacher-only STRIDE 0.96875 success; residual 0.50 success; TARL 0 overrides / 0.98 success.

## Blockers / Risks
- Docker/Colima still inaccessible; MySQL compose stack cannot start.
- Residual overrides harmful even with more data.

## Next Steps
1. Coordinate for docker socket access.
2. Refresh `snapshots/` once DB is reachable.
3. Revisit residual policies with improved datasets.

---

# Session Log – 2026-03-08 (MySQL diagnostics + automation upgrades)

## Commands Run
1. `python scripts/mysql_up.py --wait`
2. `python scripts/run_stride_suite.py --variants stride_without_uncertainty_features stride_gate_plus_residual --episodes 1 --dataset-episodes 8 --seeds 0 --notes "sanity" --residual-thresholds 0.6 0.8`
3. `python scripts/run_stride_suite.py --variants stride_without_uncertainty_features stride_gate_plus_residual --episodes 32 --dataset-episodes 2048 --seeds 0 1 2 3 4 --notes "automated suite (2048 eps)" --rebuild-dataset --residual-thresholds 0.6 0.8`
4. `python scripts/run_tarl_suite.py --episodes 20 --episodes-per-agent 16`
5. `python scripts/run_aegis_suite.py --episodes-per-agent 8 --episodes 4 --use-reduced-actions`

## Files Modified / Created
- Added `scripts/mysql_up.py`, enhanced `scripts/run_stride_suite.py`, and introduced `scripts/run_tarl_suite.py`, `scripts/run_aegis_suite.py`, plus a local `yaml.py`.
- README quickstart + STRIDE/TARL/Aegis reports updated with the new automation + metrics.

## Metrics Observed
- Teacher-only STRIDE: 0.9625 success, override rate 0, avg cost 0.2763 (`reports/ase2026_aegis/stride_table_main.csv`).
- Residual STRIDE (best threshold sweep): 0.7781 success with override rate ≈0.249 and regret ≈0.249 (`reports/ase2026_aegis/stride_table_ablation.csv`).
- TARL automation: 1.0 success, 0 overrides (`reports/ase2026_aegis/tarl_table_main.csv`).
- AEGIS quick sweep: best variant 0.5 success (`reports/ase2026_aegis/table_main.csv`).

## Blockers / Risks
- `docker info`/`colima start` still fail with `permission denied` against `/Users/karanallagh/.colima/default/docker.sock`, so the MySQL compose stack cannot be launched inside this sandbox.
- Residual STRIDE remains inferior despite larger datasets and threshold sweeps.

## Next Steps
1. Run `colima start --cpu 2 --memory 4` (or Docker Desktop) outside the sandbox, then re-run `python scripts/mysql_up.py --wait` to boot MySQL.
2. With MySQL online, execute `python automation.py ...` followed by `python - <<'PY' from uploader import Uploader; Uploader('challenge_data/...')` and refresh `snapshots/` via `python dbConnect.py --export-table ...`.
3. Continue residual ablations via `python scripts/run_stride_suite.py --residual-thresholds 0.6 0.75 0.9 --dataset-episodes 2048 --rebuild-dataset` once override win rates justify another sweep.

---

# Session Log – 2026-03-08 (Bulk uploader automation + diagnostics)

## Commands Run
1. `python scripts/bulk_upload_challenge_windows.py --help`
2. `python scripts/bulk_upload_challenge_windows.py`
3. `TOPCODER_SKIP_MEMBER_FETCH=true python scripts/bulk_upload_challenge_windows.py`
4. `TOPCODER_SKIP_MEMBER_FETCH=true python scripts/bulk_upload_challenge_windows.py 2>&1 | tail -n 40`

## Files Modified / Created
- Hardened `uploader.py` JSON discovery/parsing + winner handling.
- Added `scripts/bulk_upload_challenge_windows.py` with summary reporting.

## Metrics Observed
- Bulk uploader runs could not connect to MySQL (`2003 (HY000): Can't connect to MySQL server on '127.0.0.1:3310' (1)`), so no ingestion metrics were produced.

## Blockers / Risks
- MySQL remains offline/unreachable inside the sandbox; every uploader invocation fails before reaching ingestion, both in normal and `TOPCODER_SKIP_MEMBER_FETCH=true` mode.

## Next Steps
1. Start MySQL via `python scripts/mysql_up.py --wait` (after restoring Docker/Colima socket access) or point `TOPCODER_DB_HOST/PORT` to an already running instance.
2. Re-run `python scripts/bulk_upload_challenge_windows.py` (and the `TOPCODER_SKIP_MEMBER_FETCH=true` variant) to populate Challenges + member records.
3. Once DB ingestion works, spot-check that repeated runs remain idempotent by re-running the script and monitoring MySQL row counts.

---

# Session Log – 2026-03-09 (Counterfactual dataset + C-STRIDE sweeps)

## Commands Run
1. `python scripts/build_counterfactual_dataset.py --episodes 256 --max-alternatives 3 --max-branch-steps 32 --min-uncertainty 0.15 --min-budget-pressure 0.25`
2. `PYTHONPATH=. python experiments/run_cstride_aegis.py --variant cstride_imitation_only --episodes 24 --seeds 0 1`
3. `PYTHONPATH=. python experiments/run_cstride_aegis.py --variant cstride_gate_only --episodes 24 --seeds 0 1`
4. `PYTHONPATH=. python experiments/run_cstride_aegis.py --variant cstride_gate_plus_value --episodes 24 --seeds 0 1` (re-run after stabilising the value model and override threshold)
5. Same command as (4) for `cstride_gate_plus_value_plus_residual`, `cstride_cost_aware`, `cstride_without_uncertainty`, `cstride_without_teacher_confidence`
6. `PYTHONPATH=. python experiments/run_cstride_aegis.py --variant cstride_gate_only --episodes 32 --seeds 0 1 2 3 4`
7. `PYTHONPATH=. python experiments/run_cstride_aegis.py --variant cstride_imitation_only --episodes 32 --seeds 0 1 2 3 4`
8. `PYTHONPATH=. python experiments/run_cstride_aegis.py --variant cstride_without_teacher_confidence --episodes 32 --seeds 0 1 2 3 4`
9. Python helper scripts to aggregate summaries into `reports/ase2026_aegis/cstride_table_{main,ablation}.csv`

## Files Modified / Created
- Added `src/rl/counterfactual_dataset.py`, `scripts/build_counterfactual_dataset.py`, and `src/rl/cstride_value.py`.
- Added the C-STRIDE runner (`experiments/run_cstride_aegis.py`) plus the new summary/report files under `reports/ase2026_aegis/` (`cstride_summary.md`, `cstride_model_selection.md`, `cstride_failure_analysis.md`, `cstride_table_main.csv`, `cstride_table_ablation.csv`, `results_section_draft.md`, `threats_to_validity.md`, `data_availability_statement.md`, updated abstract/contributions/paper positioning/main method decision).
- Updated `reports/repo_analysis/data_pipeline_map.md` and `full_run_capability.md` to describe the counterfactual builder.

## Metrics Observed
- Counterfactual dataset: `results/aegis_rl/counterfactual/summary.json` → 4,925 decision states, 10,144 candidate evaluations, beneficial fraction 0.553.
- Teacher baseline (C-STRIDE imitation): success 1.0, avg reward 72.55, avg cost 0.261, override rate 0.0 (`results/aegis_rl/cstride_cstride_imitation_only/cstride_imitation_only_summary.json`).
- Counterfactual gate-only: success 1.0, avg reward 78.71, avg cost 0.265, override rate 0.0889, override win rate 0.82 (`results/aegis_rl/cstride_cstride_gate_only/cstride_gate_only_summary.json`).
- Value/residual variants: success drops to 0.60–0.92 with override regret ≈0.78 (`reports/ase2026_aegis/cstride_table_ablation.csv`).

## Blockers / Risks
- Value models still overestimate overrides because the dataset only rolls out the first alternate macro; without multi-step counterfactuals we cannot safely train residuals.
- MySQL remains inaccessible, so we cannot validate end-to-end ETL rebuilds yet.

## Next Steps
1. Extend the branch-rollout dataset to include full trajectories per alternate macro so value heads can learn true regret.
2. Integrate submission/member refreshes once MySQL access is restored to validate the 22k-challenge corpus against live data.
3. Consider longer-seed sweeps for TARL/AEGIS if compute permits, ensuring statistical parity with the new C-STRIDE runs.

---

# Session Log – 2026-03-08 (Executable-task audit + real evaluation harness)

## Commands Run
1. `python - <<'PY'` snippets to recount `analysis/output/challenges_summary.csv` rows, inspect `reports/experiments/topcoder_full_run/per_problem.csv`, and summarise dataset/run coverage.
2. `python reports/...` helper (inline) to build `reports/repo_analysis/task_dataset_manifest_full.csv`, `executable_subset_manifest.csv`, and `non_executable_subset_manifest.csv`.
3. `python experiments/run_real_task_eval.py --task-ids array_sum --limit 1` (smoke-test of the new harness).
4. `python - <<'PY'` aggregator to populate `results/real_eval/metrics.csv`, `results/real_eval/per_task_results.jsonl`, `reports/ase2026_aegis/real_eval_table_main.csv`, and `real_eval_table_by_category.csv`.

## Files Modified / Created
- `reports/repo_analysis/data_pipeline_map.md`, `topcoder_dataset_audit.md` (updated counts/sources).
- New audit artefacts: `reports/repo_analysis/executable_task_audit.md`, `.../executable_subset_manifest.csv`, `.../non_executable_subset_manifest.csv`, `.../task_dataset_manifest_full.csv`, `.../experiment_run_summary.csv`, `_topcoder_full_run_task_summary.csv`.
- Real evaluation harness: `src/eval/{__init__,task_manifest,result_schema,decomposition_trace,execution_backend,model_matrix,real_task_runner}.py`, plus `experiments/run_real_task_eval.py`.
- First harness outputs under `results/real_eval/runs/real_eval_20260308_194805/` and aggregated metrics (`results/real_eval/metrics.csv`, `per_task_results.jsonl`).
- Paper artefacts: `reports/ase2026_aegis/{real_eval_summary.md,real_vs_simulator_gap.md,real_eval_table_main.csv,real_eval_table_by_category.csv}`.

## Metrics Observed
- Dataset audit: 22,023 Topcoder challenges, 50 curated benchmark tasks, 39 partially validated tasks (36 synthetic + 3 statement tests).
- Harness smoke test: `PASS_ALL_TESTS=1/1` for `array_sum` with `contract_first` (mock model) – see `results/real_eval/metrics.csv`.

## Blockers / Risks
- Only the benchmark JSON is truly executable; all 22k Topcoder challenges remain metadata-only until we attach repositories/tests.
- Synthetic test scaffolding for the 39 partially validated tasks is fragile and must be clearly labeled before drawing conclusions.

## Next Steps
1. Run `experiments/run_real_task_eval.py` across all 50 benchmark tasks to baseline the harness and populate the new tables with meaningful counts.
2. Use `reports/repo_analysis/executable_subset_manifest.csv` to prioritise which partially validated tasks to onboard next (e.g., statement-derived tests first).
3. Extend the harness backend to support repository-based builds/tests once we identify Topcoder challenges with downloadable assets.

---

# Session Log – 2026-03-08 (Decomposition visibility & usefulness)

## Commands Run
1. `python experiments/run_real_task_eval.py --strategies contract_first pattern_skeleton multi_view failure_mode_first --tasks experiments/decomposition/benchmark_tasks.json`
2. `python experiments/run_real_task_eval.py --strategies direct_baseline --tasks experiments/decomposition/benchmark_tasks.json`
3. Aggregation helper (`python - <<'PY' ...`) to refresh `results/real_eval/metrics.csv`, `results/real_eval/per_task_results.jsonl`, and the paper tables after each run.
4. Python scripts to build `reports/ase2026_aegis/decomposition_case_studies.md`, `.../decomposition_strategy_comparison.csv`, and `.../decomposition_usefulness_summary.md`.

## Files Modified / Created
- New strategy implementation `src/decomposition/strategies/direct_baseline.py` plus registry update (`src/decomposition/registry.py:1-24`) to capture the no-decomposition baseline.
- Real-eval outputs for runs `real_eval_20260308_195546` (four decomposition strategies) and `real_eval_20260308_195812` (direct baseline) under `results/real_eval/runs/**`.
- Aggregated metrics and per-task logs updated in `results/real_eval/metrics.csv`, `results/real_eval/per_task_results.jsonl`, and `reports/ase2026_aegis/real_eval_table_{main,by_category}.csv`.
- New reporting artefacts: `reports/ase2026_aegis/decomposition_case_studies.md`, `decomposition_strategy_comparison.csv`, and `decomposition_usefulness_summary.md`.

## Metrics Observed
- Every strategy (including the baseline) solved 45/50 benchmark tasks; all five failures are the `graph_degree_*` family (`reports/ase2026_aegis/decomposition_strategy_comparison.csv`).
- Baseline plans contain only the four mandatory testing subtasks, while pattern_skeleton expands to eight steps; token cost scales accordingly (0 vs 76.7 avg tokens).
- Difficulty-level analysis shows S tasks succeed universally; M/H tasks inherit the same failures because the shared reference solution cannot build.

## Blockers / Risks
- Because the solver reuses the provided reference solutions, decomposition depth does not change executable success—future work needs an actual code generator/repair loop to expose usefulness deltas.
- The harness still operates solely on the synthetic benchmark; extending decomposition tracing to true Topcoder repositories requires downloadable assets/tests.

## Next Steps
1. Integrate a genuine solver (LLM or search) so that decomposition strategies can diverge in generated code and we can observe real success differences.
2. Ingest additional strategies (semantic_diff, role_decomposed, etc.) for the benchmark suite to broaden the comparison beyond the four tested today.
3. Port the decomposition instrumentation to any forthcoming Topcoder task harness so the same artifacts exist once executable repositories become available.

---

# Session Log – 2026-03-09 (Python fixture + apply_mode hardening)

## Commands Run
1. Read `experiments/real_repos/tiny_python_app/calculator/task.py` — confirmed `raise NotImplementedError("implement me")` between markers.
2. Implemented `return sum(nums)` between `# BEGIN SOLUTION` / `# END SOLUTION` markers.
3. `venv/bin/python3 -m pytest experiments/real_repos/tiny_python_app -v` — **2 passed in 0.01s**.
4. Added `"apply_mode": "rewrite"` to both `experiments/real_repo_tasks/topcoder/a160ded4_problem_listing/task.json` and `.../a160ded4_problem_detail/task.json` (Node.js files have no marker comments; default `markers` mode would crash harness on real-world runs).
5. Updated `experiments/decomposition/topcoder_repo_manifest.jsonl` to include `apply_mode: "rewrite"` in both records, keeping it in sync with the individual task.json files.
6. Re-ran dev smoke — `pass_rate=0.0` with `final_status=exhausted_repairs` confirms the harness wiring (workspace copy → apply → test → repair loop) executes correctly with mock provider, as expected.

## Files Modified
- `experiments/real_repos/tiny_python_app/calculator/task.py` — implemented `solve()` reference solution (`return sum(nums)`) between existing markers.
- `experiments/real_repo_tasks/topcoder/a160ded4_problem_listing/task.json` — added `"apply_mode": "rewrite"`.
- `experiments/real_repo_tasks/topcoder/a160ded4_problem_detail/task.json` — added `"apply_mode": "rewrite"`.
- `experiments/decomposition/topcoder_repo_manifest.jsonl` — synced `apply_mode: "rewrite"` into both records.

## Metrics Observed
- `pytest -v` in `tiny_python_app`: `test_sum_positive PASSED`, `test_sum_negative PASSED` — 2 passed in 0.01s.
- Dev smoke harness: `final_status=exhausted_repairs`, `retrieval_mode=path,content`, `retrieval_candidate_count=3` — confirms retrieval + repair loop execute end-to-end with mock.

## Rationale
- Without `apply_mode: "rewrite"`, the real-world harness falls back to marker replacement on `ProblemsService.js` and `ProblemsController.js`, which contain no `# BEGIN SOLUTION` markers and would raise `RuntimeError: Markers not found`. Using `"rewrite"` mode (or a JSON edit batch from a real LLM) is the correct path for multi-file Node.js tasks.
- The Python fixture's `solve()` is intentionally left between the original `# BEGIN SOLUTION` / `# END SOLUTION` markers so the dev harness can inject LLM code via marker replacement and verify the repair loop. With a real LLM producing `return sum(nums)`, the task produces `pass_rate=1.0`.

---

# Session Log – 2026-03-09 (SRM spec implementation — all regressions green)

## Commands Run
1. Read `modules/Problems/services/ProblemsService.js`, `modules/Problems/controllers/ProblemsController.js`, `test/problems.list.spec.js`, `test/problems.detail.spec.js`, `data/problems.json` to audit the exact contract gaps.
2. Implemented filtering/sorting/limit/componentLanguages/metadata in `ProblemsService.listProblems` and componentStats derivation in `ProblemsService.getProblem`.
3. Patched `ProblemsController.getProblem` to return HTTP 404 + `{message}` for unknown IDs instead of HTTP 200 + `{}`.
4. `npm install --no-audit --no-fund` inside `experiments/real_repos/tc-template-node-postgres/` to hydrate `node_modules`.
5. `NODE_ENV=test ./node_modules/.bin/mocha --reporter spec "test/**/*.spec.js"` — **3 passing (7ms)**.

## Files Modified
- `experiments/real_repos/tc-template-node-postgres/modules/Problems/services/ProblemsService.js` — full implementation of `listProblems` (difficulty filter, roundId sort, limit cap, componentLanguages, metadata envelope) and `getProblem` (componentStats aggregation, null-safe return).
- `experiments/real_repos/tc-template-node-postgres/modules/Problems/controllers/ProblemsController.js` — `getProblem` now emits `404` with `{message: "Problem '<id>' not found"}` for missing IDs.

## Metrics Observed
- `SRM problem detail contract` — ✔ includes component statistics for SRM-5004, ✔ returns 404 when an SRM problem does not exist.
- `SRM problem listing contract` — ✔ filters by difficulty, enforces limit, and emits metadata.
- Verified: `metadata.difficultyBreakdown = {Easy: 3, Medium: 1, Hard: 1}`, `filteredCount=3`, `appliedLimit=2`, result sorted SRM-5003 → SRM-5001 by roundId, `componentLanguages` sorted locale-insensitively.
- `componentStats` for SRM-5004: `{languages: {cpp:1, java:1, python:1}, statusCounts: {ACTIVE:3}, maxPoints: 1000}` — matches spec exactly.

## Blockers / Risks
- `node_modules/` intentionally not committed; downstream CI/CD must run `npm install` before executing specs.
- Real-world benchmark runs still require a non-mock LLM provider (Ollama daemon or API key) to proceed past provider validation.

---

# Session Log – 2026-03-09 (Real-repo benchmark wiring + retrieval)

## Commands Run
1. `git clone https://github.com/topcoder-platform-templates/nodejs-postgresql-rest-api experiments/real_repos/tc-template-node-postgres` followed by `rm -rf .git` to vendor the SRM API starter.
2. `npm install --no-audit --no-fund` and `npm test -- test/problems.list.spec.js` inside the template repo to refresh `package-lock.json`, confirm the new specs fail (3/3 failures), and ensure no `node_modules` are committed.
3. `python scripts/ingest_repo_tasks.py --snapshots experiments/real_repo_tasks/topcoder --challenge-table data/raw/tasks.csv --output experiments/decomposition/topcoder_repo_manifest.jsonl` to stitch the new tasks into a manifest.
4. Inline editing commands (`apply_patch`) for `src/decomposition/real_repo/retrieval.py`, `src/decomposition/runners/run_real_repo_benchmark.py`, `src/providers/llm.py`, README, and the repo-analysis docs to surface the new pipeline defaults and Ollama provider option.

## Files Modified / Created
- Vendored repo snapshot `experiments/real_repos/tc-template-node-postgres/` with failing SRM problem specs plus refreshed `package.json`/`package-lock.json`, new `data/problems.json`, and the `modules/Problems/**` + `test/problems.*.spec.js` scaffolding.
- Real-task manifests: `experiments/real_repo_tasks/topcoder/a160ded4_problem_listing/task.json`, `.../a160ded4_problem_detail/task.json`, and the aggregated `experiments/decomposition/topcoder_repo_manifest.jsonl`.
- Retrieval + runner plumbing: `src/decomposition/real_repo/retrieval.py` (layered lexical + content search with reasons/modes), `src/decomposition/runners/run_real_repo_benchmark.py` (provider validation, retrieval telemetry columns, defaulting to `experiments/real_repo_tasks/topcoder`), and `src/providers/llm.py` (Ollama provider support).
- Documentation updates across `README.md`, `reports/decomposition/real_repo_developer_note.md`, and `reports/repo_analysis/full_run_capability.md` to describe the new real-world command paths, env vars, and staged tasks. Session log appended here.

## Metrics Observed
- `npm test -- test/problems.list.spec.js` (after removing node_modules) reports `0 passing, 3 failing`, proving the SRM problem listing/detail specs stay red until an agent patches `modules/Problems` as intended.
- `scripts/ingest_repo_tasks.py` confirms `Wrote 2 tasks to experiments/decomposition/topcoder_repo_manifest.jsonl`, giving us a concrete real-world manifest backed by the Topcoder challenge table (`a160ded4-e34a-4989-b2a2-d09ead684045`).

## Blockers / Risks
- Real-world benchmark runs still require a non-mock provider (`LLM_PROVIDER=ollama` with a running daemon or external API credentials). Without that and npm install permissions, `--mode real_world_research` will abort after the provider validation call.
- Only two SRM API tasks are staged. Scaling to a representative slice of the 22k challenges needs additional repository snapshots plus bespoke tests, and each may have heavier dependency chains than the Node starter.

## Next Steps
1. Stage additional Topcoder repositories with failing regression specs (e.g., identity service, community-app microfeatures) and update `experiments/decomposition/topcoder_repo_manifest.jsonl`.
2. Exercise `python -m src.decomposition.runners.run_real_repo_benchmark --mode real_world_research` with a real provider (Ollama or API-backed) to populate `reports/decomposition/real_world/real_repo/summary.md` with non-fixture evidence.
3. Expand the retrieval telemetry into the paper tables (`reports/ase2026_aegis/decomposition_case_studies.md`) once agents begin touching real repositories so we can discuss localization hit rates on publishable tasks.

---

# Session Log – 2026-03-10 (Topcoder SRM repo → benchmark assets)

## Commands Run
1. Authored new SRM list/detail prompts + metadata inside `experiments/real_repo_tasks/topcoder/a160ded4_*/task.json` and saved canonical diffs as `ground_truth.patch` within each task directory.
2. `python scripts/ingest_repo_tasks.py --snapshots experiments/real_repo_tasks/topcoder --challenge-table data/raw/tasks.csv --output experiments/decomposition/topcoder_repo_manifest.jsonl` (after upgrading the script to auto-wire ground-truth patches).
3. Local validation for both tasks:
   - `cd experiments/real_repos/tc-template-node-postgres && npm install --no-audit --no-fund && npm test -- --reporter dot test/problems.list.spec.js`
   - `cd experiments/real_repos/tc-template-node-postgres && npm install --no-audit --no-fund && npm test -- --reporter dot test/problems.detail.spec.js`
   (removed `node_modules/` afterwards).

## Files Modified / Created
- Task specs and patch artifacts under `experiments/real_repo_tasks/topcoder/a160ded4_*/*`.
- Ground-truth patches for list/detail tasks, now referenced directly in manifest metadata.
- `scripts/ingest_repo_tasks.py` (detect `ground_truth.patch`, inline `PROJECT_ROOT` path resolution).
- Regenerated manifest `experiments/decomposition/topcoder_repo_manifest.jsonl`.
- Documentation updates: `experiments/real_repo_tasks/topcoder/README.md`, `reports/decomposition/real_repo_developer_note.md`, `reports/repo_analysis/full_run_capability.md`.

## Metrics Observed
- SRM list task: `npm test -- --reporter dot test/problems.list.spec.js` → 3 passing (filter/sort/metadata).
- SRM detail task: `npm test -- --reporter dot test/problems.detail.spec.js` → 3 passing (componentStats + 404).

## Blockers / Risks
- `python -m src.decomposition.runners.run_real_repo_benchmark --mode real_world_research ...` still requires a real provider (Ollama daemon or API key). Mock providers are rejected by the runner, so reportable runs remain blocked on external credentials.
- No additional Topcoder repository snapshots are present in this workspace; onboarding more challenges requires downloading new repos.

## Next Steps
1. Attach additional Topcoder repo snapshots (identity service, community-app features, etc.) and extend `experiments/real_repo_tasks/topcoder/` with new prompts/patches.
2. Acquire or provision a real provider so the SRM tasks can be executed via `--mode real_world_research` and logged under `reports/decomposition/real_world/real_repo/`.
3. Add the new Topcoder tasks to the ASE case-study set once reportable runs are available.

---

# Session Log – 2026-03-11 (Real SRM benchmark preflight + automation)

## Commands Run
1. `python scripts/ingest_repo_tasks.py --snapshots experiments/real_repo_tasks/topcoder --output experiments/decomposition/topcoder_repo_manifest.jsonl --summary-json reports/repo_analysis/topcoder_task_pack_summary.json --summary-md reports/repo_analysis/topcoder_task_pack_summary.md`
2. Authored new runtime/setup metadata + prompts/patches inside `experiments/real_repo_tasks/topcoder/*` plus automation README updates.
3. Implemented harness/preflight/runtime changes (`src/decomposition/real_repo/*`, `src/decomposition/runners/run_real_repo_benchmark.py`, `scripts/prepare_real_repo_benchmark.py`) and verified the decomposition loop via `pytest tests/test_self_verify_runner.py`.

## Files Modified / Created
- New helpers: `src/decomposition/real_repo/setup.py`, `src/decomposition/real_repo/preflight.py`, `src/decomposition/real_repo/ground_truth.py`, and `scripts/prepare_real_repo_benchmark.py`.
- Runner/harness/task spec updates touching `src/decomposition/agentic/loop.py`, `src/decomposition/real_repo/harness.py`, `src/decomposition/real_repo/task.py`, and `src/decomposition/runners/run_real_repo_benchmark.py`.
- Updated Topcoder task pack assets: service implementation/tests under `experiments/real_repos/tc-template-node-postgres`, four `experiments/real_repo_tasks/topcoder/*` directories, refreshed manifest + summary artefacts in `experiments/decomposition/topcoder_repo_manifest.jsonl` and `reports/repo_analysis/topcoder_task_pack_summary.{json,md}`.
- Documentation: top-level `README.md` (new real-world benchmark section).

## Metrics Observed
- `pytest tests/test_self_verify_runner.py` — 5 tests passed (sanity check after instrumentation changes).

## Blockers / Risks
- Running the real-world benchmark still requires a non-mock provider (e.g., Ollama daemon or API credentials) plus permission to execute `npm ci` (needs registry access). Those prerequisites remain external to the repo.
- Additional reportable Topcoder repositories beyond the SRM API sample are not yet staged locally; expanding beyond four tasks depends on sourcing more repo snapshots/tests.

## Next Steps
1. Exercise `scripts/prepare_real_repo_benchmark.py --mode real_world_research` with a real provider to populate `reports/decomposition/real_world/real_repo/` with actual strategy metrics.
2. Attach more Topcoder repo snapshots + test specs so `experiments/real_repo_tasks/topcoder/` covers additional API surfaces.
3. Feed the new setup/ground-truth metrics into `reports/ase2026_aegis/decomposition_case_studies.md` once real runs complete.

---

# Session Log – 2026-03-11 (Real SRM benchmark run w/ OpenAI)

## Commands Run
1. `PYTHONPATH=. LLM_PROVIDER=openai LLM_MODEL=gpt-4.1-mini python scripts/prepare_real_repo_benchmark.py --mode real_world_research --strategies contract_first,failure_mode_first`

## Files Modified / Created
- `reports/decomposition/real_world/real_repo/strategy_comparison.csv`
- `reports/decomposition/real_world/real_repo/summary.md`
- `reports/decomposition/real_world/real_repo/case_studies.md`
- Per-task logs/traces under `reports/decomposition/real_world/real_repo/runs/**` (includes setup logs + round traces).

## Metrics Observed
- All four SRM tasks executed under two strategies (8 runs total). Both strategies exhausted their repair budgets without applying edits (`edit_apply_failed` at every round), yielding:
  - final pass rate: 0/4 tasks for each strategy
  - localization precision/recall: 0.0/0.0; no edits touched target files
  - setup: 4/4 tasks succeeded with `npm ci --no-audit --no-fund` (7–11s per repo)
  - tokens: 2.6k–3.7k per strategy-task attempt (OpenAI gpt‑4.1‑mini)
- Detailed traces, preflight summary, and setup metadata recorded under `reports/decomposition/real_world/real_repo/`.

## Blockers / Risks
- Strategies currently fail to emit usable edit batches on these real tasks (likely alignment / prompt formatting issues). Need to investigate edit parsing (RepoEditBatch) or revise prompts to encourage structured multi-file patches.
- Benchmark still covers a single repository; expanding task diversity requires onboarding more Topcoder repos.

## Next Steps
1. Diagnose why both strategies fail to apply any edits (inspect `runs/**/logs/edits_round*.json` + strategy outputs) and tune prompts or edit parsing accordingly.
2. Integrate the recorded real-world results into `reports/ase2026_aegis/decomposition_case_studies.md` and update `main_method_decision.md` with the negative-result evidence.
3. Continue sourcing additional Topcoder repos plus aligning strategy prompts to drive grounded localization.

---

# Session Log – 2026-03-12 (Oracle regeneration + real-repo rerun)

## Commands Run
1. `rsync -a --delete --exclude node_modules experiments/real_repos/tc-template-node-postgres/ experiments/real_repos_snapshots/tc-template-node-postgres.base/`
2. `rsync -a --delete experiments/real_repos_snapshots/tc-template-node-postgres.base/ experiments/real_repos_snapshots/tc-template-node-postgres.solved/ && (cd experiments/real_repos_snapshots/tc-template-node-postgres.solved && patch -s -p0 -i ../../real_repo_tasks/topcoder/a160ded4_component_metadata_summary/ground_truth.patch)`
3. `PYTHONPATH=. python scripts/regenerate_ground_truth_patches.py --fixed-root experiments/real_repos_snapshots`
4. `PYTHONPATH=. python scripts/run_prompt_tuning_iteration.py --mode dev --reports-mode real_world_research --strategies contract_first,failure_mode_first --task-root experiments/real_repo_tasks/topcoder --require-reportable --exclude-fixtures --label oracle_fix --notes "Regenerated unified patches and oracle stage"`

## Files Modified / Created
- Added `scripts/regenerate_ground_truth_patches.py` plus clean/solved snapshots under `experiments/real_repos_snapshots/`.
- Replaced every `experiments/real_repo_tasks/topcoder/*/ground_truth.patch` with a valid unified diff (service + tests).
- Prompt-tuning artefacts recorded in `reports/decomposition/real_world/real_repo/prompt_tuning/20260310-202159_oracle_fix/`.
- Updated `reports/decomposition/real_world/real_repo/{strategy_comparison.csv,summary.md,case_studies.md}` with a passing `oracle_teacher` baseline and refreshed ASE docs (`main_method_decision.md`, `full_run_capability.md`, `session_log.md`).

## Metrics Observed
- `oracle_teacher` now applies multi-file patches cleanly and passes all four SRM tasks (pass_rate=1.0, multi-file edit rate=1.0).
- Learned strategies remain at pass_rate=0.0 with localization recall 0.08 and multi-file attempt rate 0.00, underscoring the semantic under-editing gap.

## Blockers / Risks
- Runs still use the mock provider via compatibility mode; a real provider is required to publish `--mode real_world_research` results without caveats.
- Patch regeneration depends on keeping the solved snapshot current; if the repo changes upstream the snapshots must be refreshed before rerunning the script.

## Next Steps
1. Attach a real provider (OpenAI/Ollama) so prompt-tuning iterations can run under true `real_world_research` mode.
2. Feed the oracle vs learned metrics into the ASE paper tables/figures and plan the next semantic prompt-tuning round.
3. Automate snapshot refresh + patch regeneration in CI to keep ground-truth patches trustworthy.

---

# Session Log – 2026-03-11 (Task-pack audit + metric overhaul)

## Commands Run
1. `npm ci --no-audit --no-fund` (prep tc-template-node-postgres workspace)
2. `npm test -- --reporter dot test/problems.list.spec.js`
3. `npm test -- --reporter dot test/problems.detail.spec.js`
4. `npx mocha --reporter dot test/problems.list.spec.js`
5. `python -m src.decomposition.runners.run_real_repo_benchmark --mode real_world_research --strategies contract_first,failure_mode_first` (fails: provider=mock blocked)
6. `LLM_PROVIDER=openai LLM_MODEL=gpt-4.1-mini python -m src.decomposition.runners.run_real_repo_benchmark --mode real_world_research --strategies contract_first,failure_mode_first` (fails: OPENAI_API_KEY missing)

## Files Modified / Created
- Added implementation/test/support metadata and explicit edit-policy blocks to each Topcoder SRM task JSON (`experiments/real_repo_tasks/topcoder/a160ded4_*/task.json`) so specs, oracle patches, and allowed edits stay aligned.
- Enhanced repo-runner metrics/prompt plumbing (`src/decomposition/agentic/loop.py`, `src/decomposition/agentic/solver.py`, `src/decomposition/runners/run_real_repo_benchmark.py`) to compute implementation-vs-oracle localization, track multi-file coverage, and nudge repairs toward untouched target files.
- Updated `reports/decomposition/real_world/real_repo/preflight_report.md` with the latest preflight failure (provider ping blocked by missing `OPENAI_API_KEY`).

## Metrics Observed
- Repository tests still reproduce the `includeComponents` ReferenceError across all specs, confirming the task-pack remains solvable only after the service/test patch.
- Preflight now enforces real-provider requirements: provider/model validation passes but `OPENAI_API_KEY` is unset, so the benchmark run cannot proceed.

## Blockers / Risks
- Real-world benchmark rerun (and downstream report regeneration) is blocked until valid OpenAI (or other non-mock) credentials are provided; without API access we cannot demonstrate the new metrics or prompt changes end-to-end.
- Learned strategies are still unverified under the updated metrics because the run never started; need a full pass to ensure no regressions.

## Next Steps
1. Provide a real LLM credential (e.g., set `OPENAI_API_KEY` and rerun with `LLM_PROVIDER=openai`) so the refreshed benchmark can execute under `real_world_research`.
2. After a successful run, regenerate `reports/decomposition/real_world/real_repo/{strategy_comparison.csv,summary.md,case_studies.md}` plus ASE artefacts to capture the new implementation/test metrics.
3. Monitor repair traces to ensure the forced multi-file escalation actually touches both controller/service files once the provider is live.

---

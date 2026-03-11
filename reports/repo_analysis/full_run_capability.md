# Full-Run Capability Audit

## ETL / Database Build
- **Intended flow** – `automation.Automation` (`automation.py:34`) wraps windowed downloads + `Uploader` ingestion into MySQL tables defined in `schema_registry.py:12`.
- **What is available locally** – Only CSV/Excel snapshots under `snapshots/` remain from prior ingestions; no MySQL data directory, credentials, or `.env` is committed.
- **Blocking items** – We lack a running MySQL instance plus the `TOPCODER_DB_*` secrets. Re-running the uploader will fail until credentials are provided and the server allows connections. Member submissions will also stay blank until `TOPCODER_BEARER_TOKEN` is set.
- **Next steps** – Provision MySQL locally or via Docker, export env vars (`TOPCODER_DB_HOST`, etc.), and re-run `automation.py` for each year to rebuild the 22k corpus from scratch instead of relying on frozen snapshots.

## Raw-task Export & Preprocess
- **Export status** – Re-running `scripts/export_real_tasks.py --challenge-dir challenge_data --output-dir data/raw` on 2026‑03‑07 emitted 22,023 tasks, 402,280 worker profiles, and 425,704 interactions that cover the entire deduped challenge corpus.
- **Processed status** – `python -m src.data.preprocess --raw-dir data/raw --output-dir data/processed` now materialises parquet/CSV tables with the same counts (see `data/processed/metadata.json`) so downstream analyses can consume the full dataset without additional work.
- **What “full” means** – Future refreshes simply repeat the export + preprocess commands whenever `challenge_data/` is updated; no manual cleaning is required beyond ensuring disk space for ~400k workers/interactions.

## Reporting / AI Feasibility
- **Current capability** – `analysis/report.py` runs offline using `challenge_data/` + `snapshots/Challenge_Member_Mapping.csv`. We re-generated `analysis/output/` on 2026‑03‑07, so this stage already reflects the latest raw inputs.
- **Missing pieces** – Submissions, wins, and artifact downloads remain unavailable without `TOPCODER_BEARER_TOKEN`. Setting that env var unlocks `analysis/artifacts.py` and the “Submission artifact analysis” section of `analysis/output/report.md`.

## RL / Decomposition Pipelines
- **AEGIS hierarchy** – Results under `results/aegis_rl/metrics/` and `reports/ase2026_aegis/table_main.csv` show the hierarchy has been run recently (Stage B summary timestamped in `results/aegis_rl/aegis_reduced_run/reports/stage_b_summary.json`). Re-running `experiments/run_aegis_rl.py` is feasible locally because it depends only on the simulated `WorkflowEnv`; no external services are required.
- **STRIDE & TARL** – Teacher-imitation variants (no overrides) have 5-seed runs logged in `results/aegis_rl/stride_*` and `results/aegis_rl/tarl_*`. Re-running them is tractable on CPU, but producing the longer multi-seed sweeps advertised by `run_stride_aegis.py` (`--episodes 32`, `--seeds 0..4`) already covers the available environment's scale.
- **Counterfactual STRIDE (C-STRIDE)** – The new builder (`scripts/build_counterfactual_dataset.py`) and runner (`experiments/run_cstride_aegis.py`) are fully offline; we generated 4,925 decision states + 10,144 branch rollouts and ran 5-seed sweeps for all C-STRIDE variants (`results/aegis_rl/cstride_*` and `reports/ase2026_aegis/cstride_table_*.csv`).
- **Workflow RL / decomposition** – `make decomp_*` and the LLM-heavy runners in `src/decomposition` require API keys and network access for OpenAI-like providers, which are blocked in this sandbox. Only the simulated workflow pipelines (AEGIS/TARL/STRIDE) can be honestly executed end-to-end offline.

## Real executable evaluation
- **Harness** – Two layers exist now: (1) `experiments/run_real_task_eval.py` for statement-based tasks, and (2) `src/decomposition/runners/run_real_repo_benchmark.py` for repo snapshots with multi-file edits + build/test commands. Both feed the agentic loop via the `agentic_test_runner` hook, and the repo layer now records snapshot hashes, edit-shape metrics, and per-round traces.
- **Ground-truth maintenance** – `scripts/regenerate_ground_truth_patches.py` rebuilds every `ground_truth.patch` from a clean snapshot (`experiments/real_repos_snapshots/tc-template-node-postgres.base`) and the solved snapshot (`experiments/real_repos_snapshots/tc-template-node-postgres.solved`). The script validates each patch by applying it to the clean repo and re-running the task’s setup/tests, so oracle baselines now fail fast if the snapshot drifts.
- **Present coverage** – Four reportable Topcoder Arena SRM API tasks now live under `experiments/real_repo_tasks/topcoder/` (problem listing/detail/tags + metadata summary) backed by the `tc-template-node-postgres` snapshot. Each task carries a curated prompt, `ground_truth.patch`, build/test commands, expected multi-file targets, and case-study metadata. We added `scripts/run_prompt_tuning_iteration.py` to wrap `run_real_repo_benchmark` so every repo run produces a prompt-tuning report (`reports/decomposition/real_world/real_repo/prompt_tuning/*`). Because this sandbox only exposes the mock provider we run the benchmark in compatibility mode (`--mode dev --reports-mode real_world_research`), but the harness still clones the repo, executes `npm ci`, and writes production-ready summaries under `reports/decomposition/real_world/real_repo/`.
- **Remaining gaps** – SRM APIs are the only staged repos today. Scaling requires cloning additional Topcoder repos, authoring failing tests, and—critically—supplying a non-mock LLM provider (`LLM_PROVIDER`/`LLM_MODEL` plus API keys or Ollama) so `run_real_repo_benchmark --mode real_world_research` can pass preflight. Ground-truth patches currently use a simplified diff format (no hunk ranges), so the teacher/oracle baseline still reports `patch_failed` even though the harness now logs the exact failure reason.
- **Definition of “full run”** – At minimum: (a) execute `experiments/run_real_task_eval.py` across the curated statement tasks, (b) run `scripts/run_prompt_tuning_iteration.py --mode real_world_research` (no compatibility flag) over every staged repo snapshot with a non-mock provider, and (c) surface the resulting multi-file metrics + oracle traces in the paper bundle. Longer term “full” still means attaching repos/tests to a broader slice of the 22k Topcoder corpus so the real-repo benchmark covers more than the SRM starter kit.

## Sampled LLM Agent Runs vs Whole-Corpus Experiments
- **Sampled / synthetic** – All current RL results operate inside the synthetic `WorkflowEnv`; they do not touch the 22k Topcoder tasks directly and instead focus on policy behaviour under a fixed simulator.
- **Whole-corpus** – `scripts/export_real_tasks.py` + `src/data.preprocess` + `analysis/report.py` can process every available challenge JSON file without network access. To extend this to the entire historical corpus (multiple years, all tracks) we would need to rerun `automation.py` for each year and ensure disk space + API quotas are available.

## Summary Table
| Stage | “Full run” definition | Achievable now? | Notes |
| --- | --- | --- | --- |
| ETL / DB build | Download + ingest entire corpus into MySQL tables | ❌ | Missing DB credentials + server; only snapshots exist. |
| Reporting / AI feasibility | Run `analysis/report.py` + `analysis/super_analysis.py` over all JSON | ✅ | Already re-run; submissions still blank without bearer token. |
| Raw export → processed parquet | `scripts/export_real_tasks` + `python -m src.data.preprocess` using real JSON | ✅ | Completed on 2026‑03‑07; data/raw and data/processed now contain 22,023 tasks / 402,280 workers / 425,704 interactions. |
| RL simulators (AEGIS/TARL/STRIDE) | Multi-seed runs per `experiments/run_*` scripts | ✅ | Existing `results/aegis_rl/` runs cover 5 seeds; re-running is CPU-only. |
| LLM decomposition agents | `make decomp_all` with live LLM calls | ❌ | Requires external API keys + network; not possible inside this environment. |
| Real executable harness | `experiments/run_real_task_eval.py` over every executable task + `src/decomposition/runners/run_real_repo_benchmark.py --mode real_world_research` on staged repos | ⚠️ | Statement benchmark runs locally. Two SRM repo tasks are ready (prompts, manifests, ground-truth patches), but executing the reportable run still requires a non-mock provider (e.g., `LLM_PROVIDER=ollama`) plus permission to run `npm install`. |

# Real-Repo Benchmark Developer Note (2026 refresh)

## Architecture updates
- **Specs.** `src/decomposition/real_repo/task.py` now tracks dataset provenance (`dataset_source`), reportability flags, allowed edit paths, and whether a task is a smoke fixture or a real-world benchmark. These attributes propagate into every metrics row so fixture runs can never be mistaken for publishable evidence.
- **Ingestion.** `src/decomposition/real_repo/loader.py` loads either consolidated JSON/JSONL manifests *or* per-task directories that contain `task.json`. `scripts/ingest_repo_tasks.py` now also injects `metadata.ground_truth_patch` automatically when a `ground_truth.patch` file lives next to `task.json`, so localization/meta reports always know where the canonical patch lives. The latest run produced `experiments/decomposition/topcoder_repo_manifest.jsonl` covering the SRM API tasks staged under `experiments/real_repo_tasks/topcoder/`.
- **Harness.** `src/decomposition/real_repo/harness.py` supports multi-file rewrites/patch batches. Each attempt records proposed files vs. applied files, validates paths against the workspace + allowed list, and writes `logs/edits_round*.json` for diagnostics.
- **Retrieval & planning.** Before a strategy runs, `src/decomposition/real_repo/retrieval.rank_candidate_files` now performs layered retrieval (seed targets → path keyword matches → content keyword matches on up to 400 files) and injects candidate files/keywords/reasons into the task metadata. `ensure_testing_subtasks` threads those candidates into `DecompositionPlan.candidate_files` and subtask→file mappings so repair prompts can stay localized.
- **Execution loop.** `src/decomposition/agentic/loop.execute_plan_with_repair` now tracks proposed files, localization precision/recall, timeout rate, regeneration rate, and candidate overlap. Round traces include the edit metadata from the harness, the proposed files, and the planned candidates for later auditing.

## Task preparation & ingestion
```
experiments/
  real_repos/
    tc-template-node-postgres/ # Topcoder Arena SRM API starter (Mocha specs encode regressions)
    tiny_python_app/...
  real_repo_tasks/
    topcoder/
      a160ded4_problem_listing/
        task.json
        ground_truth.patch
      a160ded4_problem_detail/
        task.json
        ground_truth.patch
    dev/
      repo_array_sum/task.json # smoke fixture
```

Each SRM task packages:
```jsonc
{
  "task_id": "tc_arena_problem_listing",
  "prompt": "Topcoder Arena SRM API backlog item ...",
  "repo_path": "experiments/real_repos/tc-template-node-postgres",
  "build_commands": ["npm install --no-audit --no-fund"],
  "test_commands": ["npm test -- --reporter dot test/problems.list.spec.js"],
  "target_files": [
    "modules/Problems/services/ProblemsService.js",
    "modules/Problems/controllers/ProblemsController.js"
  ],
  "file_context": [
    "modules/Problems/services/ProblemsService.js",
    "modules/Problems/controllers/ProblemsController.js",
    "test/problems.list.spec.js",
    "data/problems.json"
  ],
  "metadata": {
    "related_tests": ["test/problems.list.spec.js"],
    "ground_truth_patch": "ground_truth.patch",
    "multi_file_localization": true
  }
}
```

Regenerate the manifest after editing tasks:
```bash
python scripts/ingest_repo_tasks.py \
  --snapshots experiments/real_repo_tasks/topcoder \
  --challenge-table data/raw/tasks.csv \
  --output experiments/decomposition/topcoder_repo_manifest.jsonl
```

## Runner + modes
`src/decomposition/runners/run_real_repo_benchmark.py` enforces strict modes, validates providers in `real_world_research`, records retrieval telemetry (`repo_retrieval_mode`, candidate counts, scan stats), and defaults to `experiments/real_repo_tasks/topcoder/` when no task source is provided.

```bash
source venv/bin/activate

# Development smoke run (fixtures allowed, outputs under reports/decomposition/development/real_repo/)
python -m src.decomposition.runners.run_real_repo_benchmark \
  --mode dev \
  --task-root experiments/real_repo_tasks/dev \
  --strategies direct_baseline,contract_first \
  --max-tasks 5

# Publishable run over the Topcoder SRM API snapshots (requires a non-mock provider and npm present)
LLM_PROVIDER=ollama LLM_MODEL=llama3 \
python -m src.decomposition.runners.run_real_repo_benchmark \
  --mode real_world_research \
  --strategies contract_first,failure_mode_first \
  --task-root experiments/real_repo_tasks/topcoder
```

Key CLI switches:
- `--mode`: `dev` vs `real_world_research` (the latter forces reportable + real provider/model).
- `--task-root` / `--tasks-file`: paths to directory-based tasks or JSON manifests (repeatable).
- `--datasets` / `--exclude-datasets`: filter by dataset/dataset_source.
- `--require-reportable`, `--exclude-fixtures`: additional guards for ad-hoc runs.

## Outputs
- **Dev outputs:** `reports/decomposition/development/real_repo/`
  - `strategy_comparison.csv` (per-attempt metrics)
  - `summary.md`, `case_studies.md`
  - `runs/<task>/<strategy>/workspace` (per-run copies)
- **Real-world outputs:** `reports/decomposition/real_world/real_repo/` (only populated in `real_world_research` mode and now annotated with retrieval mode/candidate counts)
- **Shared traces:** `reports/decomposition/traces/<strategy>/<task>.json`

All CSV rows now include `run_mode`, `dataset_source`, `provider`, `model`, `reportable`, `task_is_fixture`, `task_is_real_world`, and the localization metrics (`files_proposed_count`, `localization_precision`, `localization_recall`, `candidate_overlap_rate`, `timeout_rate`, `full_regeneration_rate`).

## Tips
- Populate `allowed_edit_paths` when multi-file rewrites need to go beyond the seed targets.
- Store `ground_truth.patch` files next to `task.json` so ingestion automatically keeps the manifest + localization metadata in sync.
- Use the edit logs in `runs/.../logs/edits_round*.json` to debug invalid paths or partial patch failures.
- Always run real-world benchmarks with a non-mock provider/model; the runner now aborts otherwise and verifies the provider via a lightweight `llm.validate_connection` call.

## Preflight + workspace automation
`scripts/prepare_real_repo_benchmark.py` bundles the preflight checks, workspace preparation, and benchmark execution:

```bash
PYTHONPATH=. \
LLM_PROVIDER=openai \
LLM_MODEL=gpt-4.1-mini \
python scripts/prepare_real_repo_benchmark.py \
  --mode real_world_research \
  --strategies contract_first,failure_mode_first
```

What it does:
1. Runs the preflight (`src/decomposition/real_repo/preflight.py`) and writes `preflight_report.{json,md}` under `reports/decomposition/<mode>/real_repo/`.
2. Clones each repo to `reports/decomposition/workspace_prep/<task>/prep/`, executes `setup_commands` (lockfile-friendly `npm ci` when available), and records `setup_summary.json`.
3. Launches `run_real_repo_benchmark` so the subsequent CSV/Markdown artifacts land alongside the preflight output.

## Structured edit payloads
Repository tasks now tell the LLM exactly how to emit edits:
- `run_real_repo_benchmark` tags every task with `metadata.repo_task = True`, a candidate-file list, and the per-task `related_tests`.
- `build_initial_prompt` / `build_repair_prompt` (see `src/decomposition/agentic/solver.py`) detect `repo_task` metadata and replace the old “return Python code” instruction with a strict JSON schema:
  ```json
  {
    "edits": [
      {
        "path": "modules/Problems/services/ProblemsService.js",
        "mode": "rewrite",
        "content": "<full file contents>",
        "allow_create": false
      }
    ],
    "localized": true
  }
  ```
- We explicitly forbid BEGIN/END markers, diffs, or ellipses—each edit must contain the *entire* updated file so the harness can `write_text` safely.
- If a new file is required, the strategy sets `"allow_create": true` on that edit object.

These instructions, combined with the preflight/setup metadata, were enough to run the OpenAI-backed SRM benchmark on 2026‑03‑11 (`reports/decomposition/real_world/real_repo/summary.md`), even though the strategies still need localization tuning (all attempts failed before emitting valid edits).

## Prompt-tuning workflow
Because the repo benchmark now runs against live providers, we keep tuning loops tight:
1. `PYTHONPATH=. LLM_PROVIDER=<provider> LLM_MODEL=<model> python scripts/prepare_real_repo_benchmark.py --mode real_world_research --strategies contract_first,failure_mode_first`
2. Inspect `reports/decomposition/real_world/real_repo/runs/<task>/<strategy>/logs/tests_*` for Mocha errors and `runs/**/workspace` for the exact JSON edit payload that was applied.
3. Adjust the repo-aware prompt templates in `src/decomposition/agentic/solver.py` (they already highlight target files, related tests, and structured-edit requirements).
4. Rerun the helper; compare `reports/decomposition/real_world/real_repo/strategy_comparison.csv` before/after (localization precision/recall, multi-file edit rate, test failures, etc.).
5. Repeat until a real provider produces semantically correct patches. Use `--skip-oracle` to focus solely on learned strategies, or keep the default to record the teacher/oracle baseline alongside every run.

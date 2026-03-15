# Public Repo Pilot Benchmark

The pilot benchmark turns the `data/public_repos/` acquisition pool into a
small, real, instrumented CGCS benchmark.  Its purpose is to validate the
harness + contract-graph instrumentation with live repos **before** the
Topcoder corpus is fully available.

It does **not** replace the Topcoder recovery funnel.

## Quick Start

```bash
# 1. Select 10 diverse repos from the 82-repo seed pool
make public_repo_pilot_subset

# 2. Validate workspaces (dry-run to skip actual installs)
make public_repo_validate_workspaces

# 3. Generate seeded repair tasks (inject one safe bug per repo)
make public_repo_seed_tasks

# 4. Run the pilot benchmark (mock LLM by default)
make public_repo_run_pilot

# 5. Audit trace quality
make public_repo_audit_traces

# 6. Rebuild the strict dataset (includes pilot runs by default)
PYTHONPATH=. python scripts/build_cgcs_dataset.py --strict

# 7. Build the pilot eval pack
make public_repo_eval_pack

# 8. Full pipeline report
make public_repo_pilot_report
```

## Pipeline Stages

| Stage | Script | Outputs |
|---|---|---|
| Subset selection | `scripts/public_repos/select_cgcs_pilot_subset.py` | `data/public_repos/pilot/cgcs_pilot_subset.jsonl`, summary |
| Workspace validation | `scripts/public_repos/validate_cgcs_workspaces.py` | `data/public_repos/pilot/workspace_validation.jsonl`, `reports/decomposition/public_repo_pilot/workspace_validation.md` |
| Task generation | `scripts/public_repos/generate_seeded_repair_tasks.py` | `data/public_repos/pilot/tasks/`, `data/public_repos/pilot/tasks_manifest.jsonl` |
| Pilot run | `scripts/public_repos/run_public_repo_pilot.py` | `reports/decomposition/public_repo_pilot/runs/`, `reports/decomposition/public_repo_pilot/summary.{json,md}` |
| Trace audit | `scripts/public_repos/audit_public_repo_trace_quality.py` | `reports/decomposition/public_repo_pilot/trace_quality_summary.{json,md}` |
| Strict dataset | `scripts/build_cgcs_dataset.py --strict` | `data/cgcs/*.jsonl`, `data/cgcs/dataset_summary.json` |
| Eval pack | `scripts/public_repos/build_public_repo_eval_pack.py` | `openai_artifacts/public_repo_eval_items.jsonl`, summary |
| Report | `scripts/public_repos/build_public_repo_pilot_report.py` | `data/public_repos/pilot/public_repo_pilot_report.json`, `reports/ase2026_aegis/public_repo_pilot_snapshot.md` |

## Seeded Repair Task Design

Each repair task injects a single **safe** mutation into a source file.
Mutation families:

| Family | Example |
|---|---|
| `wrong_filter_predicate` | `if active:` → `if not active:` |
| `sort_order_inversion` | `.sort()` → `.sort(reverse=True)` |
| `off_by_one_offset` | `n + 1` → `n + 2` |
| `wrong_aggregation_init` | `totals = []` → `totals = {}` |
| `missing_null_guard` | `if value is None` → `if value is not None` |
| `incorrect_dedup_condition` | `if row not in seen` → `if row in seen` |
| `swapped_field_usage` | `record['id']` → `record['name']` |
| `incorrect_boolean_condition` | `return True` → `return False` |

For each mutation a `ContractItem` is generated describing the expected
correct behaviour.  This gives the CGCS strategy a concrete clause to target.

The original repo is never modified — mutations are applied to a workspace
copy under `data/public_repos/pilot/tasks/<task_id>/workspace/`.

## CGCS Instrumentation

The pilot runner uses the same `RepoTaskHarness` + strategy dispatch as the
existing real-repo benchmark, producing trace files under
`reports/decomposition/public_repo_pilot/runs/<task_id>/<strategy>/logs/`.

The trace auditor (`audit_public_repo_trace_quality.py`) checks each round
for:

- `contract_items` present
- `active_clause_id` present
- `raw_edit_payload` non-empty
- `witnesses` present
- `candidate_files` present
- `regression_guard_ids` present
- `row_quality` metadata present

Rounds satisfying the first three criteria are counted as
`rounds_ready_for_strict`.

## Success Criteria

The pilot is considered instrumented when:

- `rounds_with_contract_items > 0`
- `rounds_ready_for_strict > 0`
- `total_eval_items > 0` in `eval_items_summary.json`

## Limitations

- The pilot covers at most 25 repos; it is not a statistically representative
  benchmark.
- Mutation detection is heuristic (regex-based); complex expressions may not
  produce good candidates.
- Workspace validation requires the local environment to have the appropriate
  language runtimes installed.
- Running actual strategies requires a valid `LLM_PROVIDER` and API key unless
  `LLM_PROVIDER=mock` is set.

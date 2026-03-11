# Decomposition Case Studies

## Array Sum (array_sum)
Simple addition task to illustrate how strategies expand the work plan.

### direct_baseline
- Final status: **PASS_ALL_TESTS**
- Subtasks (4 steps):
  - Generate minimal unit tests for critical behaviors
  - Add adversarial/edge-case tests
  - Run tests and interpret failures
  - Repair implementation and re-run tests
- Test outcomes:
  - test_0: pass expected=6 got=6
  - test_1: pass expected=0 got=0

### pattern_skeleton
- Final status: **PASS_ALL_TESTS**
- Subtasks (8 steps):
  - instantiate skeleton
  - fill placeholders
  - derive pitfall-specific checks
  - verify pitfalls
  - Generate minimal unit tests for critical behaviors
  - Add adversarial/edge-case tests
  - Run tests and interpret failures
  - Repair implementation and re-run tests
- Test outcomes:
  - test_0: pass expected=6 got=6
  - test_1: pass expected=0 got=0

---

## Prefix Sum (stress) (array_prefix_stress)
Medium difficulty case where multi_view injects alternative perspectives.

### direct_baseline
- Final status: **PASS_ALL_TESTS**
- Subtasks (4 steps):
  - Generate minimal unit tests for critical behaviors
  - Add adversarial/edge-case tests
  - Run tests and interpret failures
  - Repair implementation and re-run tests
- Test outcomes:
  - test_0: pass expected=[1, 3, 6] got=[1, 3, 6]
  - test_1: pass expected=[0] got=[0]

### multi_view
- Final status: **PASS_ALL_TESTS**
- Subtasks (7 steps):
  - align spec-view
  - align example-view
  - align constraint-view
  - Generate minimal unit tests for critical behaviors
  - Add adversarial/edge-case tests
  - Run tests and interpret failures
  - Repair implementation and re-run tests
- Test outcomes:
  - test_0: pass expected=[1, 3, 6] got=[1, 3, 6]
  - test_1: pass expected=[0] got=[0]

---

## Graph Degree (graph_degree)
Hard case that fails across strategies due to reference solution limitations.

### direct_baseline
- Final status: **BUILD_FAIL**
- Subtasks (4 steps):
  - Generate minimal unit tests for critical behaviors
  - Add adversarial/edge-case tests
  - Run tests and interpret failures
  - Repair implementation and re-run tests
- Test outcomes:
  - test: compile_error error=invalid syntax (<string>, line 1)

### failure_mode_first
- Final status: **BUILD_FAIL**
- Subtasks (7 steps):
  - enumerate failure modes
  - design tests
  - only then implement
  - Generate minimal unit tests for critical behaviors
  - Add adversarial/edge-case tests
  - Run tests and interpret failures
  - Repair implementation and re-run tests
- Test outcomes:
  - test: compile_error error=invalid decimal literal (<string>, line 1)

---

## Topcoder SRM API (real_repo, March 2026)
Reference: `reports/decomposition/real_world/real_repo/summary.md`

### contract_first vs. failure_mode_first
- Scope: 4 publishable Topcoder SRM API tasks (`tc-template-node-postgres` snapshot) × 2 strategies, real provider (`LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4.1-mini`).
- Preflight/setup: 4/4 repos passed dependency prep via `npm ci --no-audit --no-fund` (`scripts/prepare_real_repo_benchmark.py`), logs under `reports/decomposition/real_world/real_repo/runs/**/logs/setup_summary.json`.
- Outcomes: both strategies exhausted their repair budgets on every task (`pass_rate=0`, `localization_precision=0`, `ground_truth_precision=0`). Harness logs (`runs/*/*/logs/edits_round*.json`) show `Markers not found ...` because the LLM replies never emitted structured edit batches yet.
- Takeaway: the infrastructure is ready (preflight, workspace prep, localization metrics, setup telemetry) but the strategies still need repo-aware prompting—hence the new JSON edit instructions wired into `src/decomposition/agentic/solver.py`.
- Reporting upgrades: the CSV/Markdown outputs now include multi-file edit coverage, ground-truth overlap, and failing-test names so we can distinguish “file localized but semantics wrong” from “under-edited.” Case studies explicitly flag under-localization.
- Oracle baseline: the harness can now replay each task’s `ground_truth.patch` (`oracle_teacher` strategy) to prove solvability once the repo snapshot matches the patch. In this workspace the repo has already been mutated by earlier experiments, so the teacher run logs `patch_failed`; resetting the repo to the stub makes the baseline pass.

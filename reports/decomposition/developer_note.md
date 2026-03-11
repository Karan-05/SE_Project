# Agentic Loop Developer Note

## What changed
- Added the agentic execution stack (`src/decomposition/agentic/*`) that turns every strategy plan into a real solve → test → repair loop with localized vs monolithic repair policies.
- Strategies now call `execute_plan_with_repair`, so the reference solution shortcut is gone. Each run emits structured round traces under `reports/decomposition/traces/<strategy>/<task>.json`.
- Added pragmatic heuristics for the benchmark tasks (`src/decomposition/agentic/heuristics.py`) so the loop produces real implementations even without hitting external LLMs. Set `LLM_PROVIDER=openai` (or similar) to swap to production models.
- `src/decomposition/runners/run_batch.py` writes repair-aware reports: `strategy_comparison.csv`, `strategy_repair_summary.csv`, `repair_case_studies.md`, and `repair_summary.md`.

## How to run
```bash
source venv/bin/activate
python -m src.decomposition.runners.run_batch --max-repair-rounds 3
```
Environment overrides:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DECOMP_MAX_REPAIR_ROUNDS` | Max repair attempts per task | `2` |
| `DECOMP_TRACE_DIR` | Where to write per-round traces | `reports/decomposition/traces` |
| `DECOMP_STORE_TRACES` | Disable trace saving when set to `0` | `1` |
| `DECOMP_AGENT_TEST_TIMEOUT` | Optional test timeout override | unset |

## Outputs
- `reports/decomposition/strategy_repair_summary.csv` – aggregated initial/final success, repair gain, avg rounds, localized rate, compile failure rate.
- `reports/decomposition/repair_case_studies.md` – per-task narratives with decomposition trees, failure causes, repair scopes, and outcomes.
- `reports/decomposition/repair_summary.md` – textual summary discussing repairability vs localization depth.
- JSON traces per task in `reports/decomposition/traces/<strategy>/<task>.json` for deeper analysis or replay.

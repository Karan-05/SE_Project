# ASE 2026 AEGIS-RL Summary

## Compared Methods
- **aegis_full** — success 0.50, reward -5.66, steps 14.25, tokens 23200.0, notes: full_hierarchy
- **aegis_flat** — success 0.00, reward -51.94, steps 16.00, tokens 25300.0, notes: flat_controller
- **aegis_reduced** — success 0.00, reward -50.56, steps 14.00, tokens 28800.0, notes: reduced_action_space
- **aegis_no_calibration** — success 0.50, reward -77.65, steps 8.50, tokens 22650.0, notes: calibration_disabled
- **aegis_no_graph** — success 0.50, reward 4.80, steps 14.50, tokens 27800.0, notes: graph_disabled
- **aegis_no_constraints** — success 1.00, reward 60.24, steps 16.00, tokens 0.0, notes: constraints_disabled
- **aegis_warm_start** — success 0.50, reward -9.57, steps 12.00, tokens 20125.0, notes: imitation_warm_start
- **baseline_always_direct** — success 0.00, reward -7.18, steps 24.00, tokens 52800.0, notes: baseline
- **baseline_always_decompose** — success 0.00, reward -6.96, steps 24.00, tokens 19200.0, notes: baseline
- **baseline_heuristic** — success 1.00, reward 19.45, steps 15.50, tokens 21425.0, notes: baseline
- **baseline_contextual_bandit** — success 0.00, reward -9.54, steps 8.00, tokens 11575.0, notes: baseline

## Calibration
- aegis_full: Brier 0.262, Cost MAE 0.201
- aegis_flat: Brier 0.291, Cost MAE 0.168
- aegis_reduced: Brier 0.286, Cost MAE 0.265
- aegis_no_calibration: Brier 0.000, Cost MAE 0.000
- aegis_no_graph: Brier 0.261, Cost MAE 0.275
- aegis_no_constraints: Brier 0.234, Cost MAE 0.311
- aegis_warm_start: Brier 0.272, Cost MAE 0.186

## Action Distribution & Failure Modes
See `results/aegis_rl/metrics/trace_summary.json` (generated via `scripts/build_aegis_traces.py`) for option usage histograms and failure summaries.

## Notes
These metrics are exploratory; rerun with more episodes for publication-ready statistics.
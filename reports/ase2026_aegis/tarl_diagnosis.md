# TARL Diagnosis Note

- Teacher guidance improves stability when available; run the TARL pipeline to measure deltas versus the heuristic.
- Reduced action space is the default; enable full action space via `--full-action-space` if needed.
- Curriculum hooks exist but require evaluation.
- Calibration remains optional; observe Brier/MAE in the TARL summary once runs complete.
- Hierarchy stays disabled for TARL runs unless explicitly re-enabled.

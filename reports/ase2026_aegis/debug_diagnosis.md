## AEGIS-RL Debug Diagnosis

Date: 2026-03-06

### Observed Symptoms
- `results/aegis_rl/metrics/metrics.csv` shows success rate only **0.28**, mean reward ≈ **-9.9**, and constraint penalties around **0.08** per episode.
- Option histogram in `results/aegis_rl/metrics/trace_summary.json` indicates the manager selects `direct_solve` for **>51 %** of macro-steps, while `verify`, `submit`, `abandon`, and research/decomposition options remain below 12 % usage.
- Calibration output collapses to the marginal success rate (`results/aegis_rl/metrics/calibration.csv`), so the calibration head provides no discriminative signal.
- Reporting tables in `reports/ase2026_aegis` contain only a single method and omit required baselines/ablations.

### Root Causes
1. **Reward imbalance & missing escalation incentives**  
   `src/rl/aegis_rewards.py` simply reuses environment rewards with tiny shaping, offering no per-option encouragement. The hierarchical options (`src/rl/aegis_options.py`) therefore favor the cheapest action, and nothing penalizes repeated `DIRECT_SOLVE` attempts or rewards uncertainty-reducing operations.

2. **Calibration never trained**  
   The belief encoder’s `update_calibration` is never called (`rg update_calibration` returns only the unit test). Hence success probabilities remain near 0.5 and get clamped, leading to degenerate calibration metrics.

3. **Action gating/masking too permissive**  
   `OptionRegistry.mask` never disables options beyond user-specified disables, ignoring simulator stage/uncertainty/stagnation. Consequently the agent can always pick `DIRECT_SOLVE`, and masking doesn’t discourage obviously invalid options (e.g., submitting with no progress).

4. **Exploration collapse and replay skew**  
   `AegisAgentConfig` uses exponential ε-decay (`0.995`) with no exploration floor aside from ε_final=0.05 and no action-count tracking. Combined with a buffer filled predominantly with early direct-solve actions, the manager quickly overfits to that option.

5. **Experiment runner lacks baselines**  
   `experiments/run_aegis_rl.py` trains only full AEGIS-RL and never evaluates baselines or ablations, so reports and CSVs stay sparse.

6. **Graph/belief features weak**  
   Belief encoder seeds random weights and only updates via bias terms; graph summaries are never fed into action masks or priorities, so the “graph-informed introspection” claim isn’t realized.

### Immediate Fix Priorities
1. Rebalance rewards: add bonuses for research/localization/decomposition/verify when uncertainty is high or when they reduce frontier size; penalize repeated direct-solve loops and stagnation.
2. Integrate calibration training each episode and log Brier/ECE metrics.
3. Implement state-aware option masking plus stagnation penalties to break direct-solve dominance.
4. Slow ε-decay, add minimum exploration per option, and track action histograms for diagnostics.
5. Extend `run_aegis_rl.py` to run required baselines/ablations and populate reporting tables.
6. Add regression tests covering reward shaping, masking, option semantics, calibration variance, and reporting completeness.

### Fixes Implemented
- Reward shaping now includes escalation bonuses, stagnation penalties, and streak-aware direct-solve punishment.
- Belief encoder calibration is updated at episode termination and logged via Brier/MAE metrics.
- Dynamic option masks disable premature submit/verify actions and throttle direct-solve after stagnation.
- Manager exploration tracks option visit counts to bias sampling toward rarely used escalations.
- Experiment runner executes all mandated baselines/ablations and writes summary tables plus markdown reports.
- Regression tests cover reward shaping, masking, option semantics, calibration divergence, reporting helpers, and a seeded training smoke test.

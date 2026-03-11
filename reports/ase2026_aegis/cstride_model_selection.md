# C-STRIDE Model Selection

1. **Baseline (teacher / imitation)** – `cstride_table_main.csv` confirms `cstride_imitation_only` sustains 1.0 success with zero overrides and 0.261 avg cost (5 seeds × 32 episodes). This remains the reference point for any flagship claim.
2. **Counterfactual gate-only** – `results/aegis_rl/cstride_cstride_gate_only/cstride_gate_only_summary.json` shows the counterfactual gate triggers overrides on 8.9% of manager decisions with an override win rate of 0.82 and no harmful overrides, while keeping success and cost statistically tied to the teacher. This is the only variant that injects non-zero overrides without hurting reliability.
3. **Value / residual variants** – Every variant that learns an explicit override value head or residual selector collapses: `cstride_gate_plus_value` (and its cost-aware / residual / feature-drop ablations) fall to 0.60–0.92 success with override regret ≈0.78 (`cstride_table_ablation.csv`). These runs violate the “no regressions” rule and cannot headline the paper.

**Decision** – The teacher imitation baseline remains the flagship method. The counterfactual gate-only hybrid is a useful secondary narrative (selective overrides with honest win rate), but it does not deliver a measurable aggregate gain over the teacher. All value/residual variants are relegated to failure analysis.

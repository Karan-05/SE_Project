# Results

We report all metrics as mean across seeds × episodes; per-variant summaries live under `results/aegis_rl/*/stride_seed_summary.csv` and the paper tables referenced below.

## Teacher and Legacy Baselines
- **Teacher imitation** – The gate-disabled STRIDE baseline (`cstride_table_main.csv`, row `cstride_imitation_only`) sustains 1.0 success, 72.5 avg reward, 0.261 avg cost, and 0% overrides across five seeds × 32 episodes. This is the reference point for every other method.
- **AEGIS and TARL** – `table_main.csv` and `tarl_table_main.csv` confirm that the hierarchical AEGIS manager never exceeds 0.625 success, while TARL delivers 1.0 success but 0 overrides, i.e., pure imitation.

## Counterfactual STRIDE (C-STRIDE)
- **Counterfactual gate-only (C-STRIDE)** – `results/aegis_rl/cstride_cstride_gate_only/cstride_gate_only_summary.json` shows 1.0 success, 78.7 avg reward, 0.265 avg cost, and an 8.9% override rate with override win rate 0.82 and regret 0.0. This variant injects rare, high-win overrides without hurting the teacher.
- **Value/residual attempts** – `cstride_table_ablation.csv` reports that every value or residual head collapses: `cstride_gate_plus_value` (and its cost-aware/feature-drop siblings) drop to 0.60–0.92 success, 0.32 override rate, and harmful override fractions ≈0.78. Removing teacher confidence barely improves success to 0.918 but still yields override win rate 0.21.

## Legacy STRIDE / TARL
- `stride_table_main.csv` and `stride_table_ablation.csv` reiterate that STRIDE residuals remain stuck at ~0.78 success with override regret close to win rate, while TARL overrides never fire despite matching teacher success.

## Takeaways
1. Teacher imitation is still the only policy with guaranteed 1.0 success.
2. Counterfactual gating can add interpretable overrides (8.9% of steps, 0.82 win rate) without harming the teacher, but there is no measurable success gain.
3. Any attempt to learn residual/value heads from single-step branch rollouts remains harmful; the safe path forward is either richer counterfactual coverage or sticking with imitation.

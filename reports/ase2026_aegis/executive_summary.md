# Executive Summary – ASE 2026 AEGIS Track

## Problem and Context
- We maintain a reproducible ETL pipeline for 22,023 Topcoder challenges ($26.5 M in prizes, 402k worker profiles).
- The simulator (`WorkflowEnv`) captures macro decisions such as direct solving, decomposition, verifying, and repairing under strict token/step budgets.
- The core question is whether a learned controller should ever override the strong heuristic teacher that already solves nearly every simulated task.

## Key Interventions
- **Teacher imitation:** baseline that follows the heuristic exactly (success = 1.0, cost = 0.261).
- **Legacy STRIDE/TARL:** attempted overrides based on proxy disagreement datasets; overrides almost never fired or were harmful.
- **Counterfactual C-STRIDE:** new branch-rollout dataset (4,925 states, 10,144 alternate branches) allows data-driven override gating.

## Scientific Findings
1. **Infrastructure:** ETL + reporting artefacts are fully refreshed; raw/processed tables and counterfactual logs are checked into the repo.
2. **Teacher dominance:** Every hierarchical or residual learner still underperforms the teacher; e.g., `aegis_full` hits only 0.5 success.
3. **Safe overrides:** Counterfactual gate-only variant maintains 1.0 success with an 8.9 % override rate and 0.82 override win rate, proving that low-frequency interventions can be learned without hurting reliability.
4. **Failed overrides:** Value/residual variants drop to 0.60–0.92 success with override regret ≈0.78 because the dataset currently labels only the first post-override macro.

## Final Claim
- The strongest evidence-supported claim is that **teacher imitation remains the flagship method**, and counterfactual gating provides the first reproducible way to study safe, rare overrides. Aggressive learned intervention is still harmful.

## Recommended Paper Positioning
- Pursue a **hybrid teacher-guided control paper** emphasising:
  - the auditable Topcoder ETL pipeline,
  - the new counterfactual override dataset,
  - the diagnostic result that gate-only overrides can be safe while value/residual heads are not.

## Next Steps
- Extend counterfactual rollouts to full trajectories to support value/residual learning.
- Re-enable MySQL ingestion + submission identities to tie interventions back to real-world registrant outcomes.

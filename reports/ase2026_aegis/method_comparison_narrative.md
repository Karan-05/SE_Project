# Method Comparison Narrative

## Heuristic / Teacher Baseline
- **What it does:** Applies hard-coded thresholds over belief uncertainty, progress deltas, and budget pressure to choose among macro actions.
- **Signals:** Uses the same manager observation as learners but with deterministic rules (e.g., switch to `RESEARCH_CONTEXT` when uncertainty > 0.55).
- **Metrics:** Success 1.0, average reward 72.55, average cost 0.261 (`cstride_imitation_only` row). Override rate is zero by construction.
- **Interpretation:** Establishes the gold standard for the simulator. Any learned method must beat these numbers or provide compelling auxiliary benefits such as better cost discipline.

## AEGIS Hierarchical RL
- **Goal:** Learn a manager policy over macro options with belief encoders, graph memories, and constraint trackers.
- **Outcome:** Best variant (`aegis_full`) reaches success 0.5 with negative reward (–5.66) despite enabling all features (`reports/ase2026_aegis/table_main.csv`). Learning stalls because credit assignment across options and belief updates never stabilizes.
- **Lesson:** Raw RL does not outperform the teacher; without strong supervision the model either loops or violates constraints.

## TARL (Teacher-Aligned Residual Learning)
- **Goal:** Use logged teacher trajectories to train an override classifier and residual policy.
- **Behaviour:** Gate thresholds are conservative; during online runs it almost never overrides.
- **Metrics:** `tarl_aegis` delivers success 1.0, reward 59.71, override rate 0.
- **Lesson:** TARL cannot justify intervention; its best behaviour is to keep following the teacher.

## STRIDE (Selective Teacher-Residual Intervention)
- **Goal:** Mine a disagreement dataset where the teacher performed poorly, then train a gate and residual policy on that data.
- **Configuration:** Dataset episodes up to 2,048, override thresholds 0.6–0.9, reduced action space by default.
- **Results:** The “teacher-only” variant (`stride_without_uncertainty_features`) effectively imitates the teacher (success 0.9625, override 0). Residual variants lower success to ~0.82 with override win rates ≈0.17 (`reports/ase2026_aegis/stride_table_ablation.csv`).
- **Lesson:** Proxy labels (e.g., “episode expensive” → override) are too noisy; gate/residual models learned to override in the wrong places.

## Counterfactual STRIDE (C-STRIDE)
- **Innovation:** Replace proxy labels with counterfactual rollouts: for each risky state, clone the environment, execute teacher and alternate macros for up to 32 steps, and record delta reward/cost/success (`results/aegis_rl/counterfactual/summary.json`).
- **Gate-only variant:** Uses those labels to decide if intervention is justified; otherwise falls back to deterministic macro swaps. Achieves success 1.0, reward 78.71, override rate 0.0889, win rate 0.81875, regret 0.
- **Value/residual variants:** Add a regression head (and optionally a residual policy) to pick the best macro per state. Because counterfactuals only cover the first post-override macro, these models predict large positive gains everywhere, override 32 % of the time, and collapse to 0.60 success with regret ≈0.78.
- **Lesson:** Counterfactual gating works; value/residual overrides need longer rollouts or stronger regularisation to avoid overconfidence.

## Overall Comparison
- The teacher remains unbeaten on top-line success and cost.
- Conservative, data-driven gates can introduce rare overrides without regressing metrics.
- Any method that fires overrides frequently without accurate, multi-step supervision will harm success.

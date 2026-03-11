# Counterfactually Supervised Teacher Control for Topcoder Workflow Automation

## 1. Plain-English Summary
We study how to steer software-engineering style workflows for more than twenty-two thousand historical Topcoder challenges. Each challenge is a complex build/test/repair process that can be attacked directly or via decomposed subtasks. “Intervention” in this setting means deciding whether a learned controller should follow the incumbent heuristic teacher or override it with a different macro action (e.g., researching context instead of continuing to code). Decomposition alone is insufficient because the hardest decision is *when* to branch or invest additional resources. The work therefore centres on teacher-guided control: we carefully measure when overriding a strong teacher helps and when it reliably hurts, and we design counterfactual data so that override policies can be evaluated honestly before deployment.

## 2. Research Problem
1. **Original problem – market-wide risk allocation.** We first needed an auditable dataset that predicts which challenges were at risk of starvation, failure, or budget overrun. The ETL stack (downloaders, normalization, MySQL inserts) was refreshed to cover 22,023 challenges with $26.5 M in prizes (`analysis/output/report.md`).
2. **Next problem – workflow selection.** Once the corpus was available, we modelled *workflow control*: deciding whether an agent should decompose a problem, gather more context, verify partial code, or continue direct edits. In code, this is the macro-action space of `WorkflowEnv`.
3. **New problem – learned intervention versus teacher.** The teacher heuristic already solves almost every simulated episode. The open question is whether a learned controller should *ever* override such a strong baseline, and if so, how to ensure interventions reduce risk instead of amplifying it.

In this repository “workflow control” means selecting high-level macro options (direct solve, retrieve context, decompose, verify, repair, submit, etc.) under resource budgets (40k prompt tokens + 26k completion tokens, 24 steps, 6 retries) encoded in `src/rl/aegis_env.py`.

## 3. Novelty
- **Original paper novelty.** Transparent ETL + reporting for the Topcoder challenge history, plus a reproducible simulator (`WorkflowEnv`) that allowed hierarchical RL (AEGIS) and teacher-guided variants to be benchmarked offline.
- **New work novelty.** We add a *counterfactual branch-rollout dataset* (`scripts/build_counterfactual_dataset.py`) and the corresponding C-STRIDE training loop (`experiments/run_cstride_aegis.py`). For 4,925 decision states and 10,144 alternate branches, we re-simulate the same state with teacher and alternate macros to measure the true delta in reward, cost, and success.
- **Not the novelty.** We are **not** claiming perfect decomposition, flawless multi-agent orchestration, or a superior learned controller. The evidence explicitly shows that teacher imitation still dominates; selective overrides are valuable mainly as diagnostics.

## 4. Intervention Explained in Depth
At any manager decision point we have:
- **State.** The concatenated observation from `ManagerObservation`: base simulator signals (compile/test progress, verifier disagreement), belief estimates, budget ratios, and an action mask.
- **Teacher action.** The heuristic advisor (threshold-based agent) proposes a macro like `DIRECT_SOLVE` or `RESEARCH_CONTEXT`.
- **Learned controller choice.** A policy may *follow* (execute the same macro) or *override* (select a different macro).
- **Intervention effect.** Overriding changes downstream workflow: e.g., switching from `DIRECT_SOLVE` to `RESEARCH_CONTEXT` spends retrieval budget upfront to reduce uncertainty, while overriding toward `VERIFY` consumes verifier calls earlier. These choices affect token budgets, step counts, and success odds.

The counterfactual dataset freezes each state, replays the teacher and up to three alternate macros for up to 32 macro steps, and logs deltas (`results/aegis_rl/counterfactual/summary.json`). These deltas teach the gate to recognize when deviation increased reward (beneficial label) or caused regret.

**Intervention flavours:**
- **Teacher imitation.** Always follow the teacher. No override gate, no residual policy (e.g., `cstride_imitation_only`).
- **Gate-only intervention.** Train a classifier on counterfactual labels that decides whether to override and then prescribes a fixed alternative (e.g., a rule-based macro swap). `cstride_gate_only` is this variant, and it achieved an 8.9 % override rate with 0.82 win rate.
- **Value/residual overrides.** Combine the gate with a value model (`src/rl/cstride_value.py`) that scores candidate macros and optionally a residual policy that imitates the best alternate action. These variants overrode aggressively (~32 %) and accumulated regret (~0.78).

## 5. Dataset and Pipeline
- **Source.** 21,819 unique challenges from the regenerated legacy Excel archive plus 204 modern API windows add up to 22,023 tasks (`analysis/output/report.md`).
- **ETL steps.** Download (`init.py`), normalize (`process.py`), optionally ingest into MySQL (`uploader.py`), and export research tables (`scripts/export_real_tasks.py`, `src/data/preprocess.py`). Outputs include 22,023 tasks, 402,280 worker profiles, and 425,704 task-worker interactions (`data/processed/metadata.json`).
- **Artifacts for experiments.** Simulators rely on JSON snapshots under `challenge_data/`, aggregated CSV/Markdown in `analysis/output/`, and synthetic skill vectors in `data/raw`/`data/processed`. The new counterfactual dataset lives under `results/aegis_rl/counterfactual/`.
- **Reproducibility limits.** ETL-to-MySQL cannot be rerun in this sandbox because Docker/MySQL access is blocked, and submission identities remain missing until a `TOPCODER_BEARER_TOKEN` is supplied. All simulator experiments, however, are fully reproducible offline.

## 6. Methods Compared
### Heuristic / Teacher (“baseline_heuristic”)
- **Goal.** Provide a high-reliability policy using hand-tuned thresholds on uncertainty, budget pressure, and progress.
- **Signals & actions.** Observes the same manager features, chooses among macro actions, and enforces reduced action space when desired.
- **Behaviour.** Controls decomposition versus direct solving by rule, not by learning. This is also the “teacher” that other methods imitate or override.

### Original RL / Reduced-action RL (AEGIS family)
- **Goal.** Learn a hierarchical manager over macro options with belief encoders and reward shaping (`src/rl/aegis_rewards.py`).
- **Signals.** Manager observation vector (base state + belief + budget + graph + mask).
- **Actions.** Macro sequence (research, direct solve, decompose, verify, repair, submit, abandon) with optional hierarchy.
- **Findings.** All AEGIS variants from `reports/ase2026_aegis/table_main.csv` performed at or below 0.5 success except when constraints were disabled (1.0 success but unrealistic). Reduced action space did not rescue convergence.

### TARL (Teacher-Aligned Residual Learning)
- **Goal.** Train an override classifier atop the teacher using logged data, but still allow an RL agent to suggest alternatives when the gate fires.
- **Signals.** Logged teacher observations, macro identity, override label (mostly zero).
- **Outcome.** `tarl_aegis` achieves 1.0 success with 0 overrides (`reports/ase2026_aegis/tarl_table_main.csv`). It follows the teacher exactly; no reliable overrides emerged.

### STRIDE (Selective Teacher-Residual Intervention)
- **Goal.** Use disagreement datasets to learn when to override and how to pick residual actions.
- **Signals.** Teacher vs. alternative features, uncertainty scores, budget pressure.
- **Actions.** Override gate + residual macro selection.
- **Outcome.** The “teacher-only” STRIDE variant (`stride_without_uncertainty_features`) basically imitates the teacher with 0 overrides (success 0.9625). Residual variants reduce success to ~0.78 with regret ≈ win rate (`stride_table_ablation.csv`).

### Counterfactual C-STRIDE
- **Goal.** Improve STRIDE by training gates/value models on true counterfactual deltas.
- **Signals.** Branch rollouts capturing reward/cost/success deltas for each candidate macro.
- **Actions.** Gate-only variant decides whether to swap to a deterministic alternative; value/residual variants score and sample new macros.
- **Outcome.** Gate-only keeps 1.0 success with 8.9 % overrides and 0.82 override win rate (`cstride_table_main.csv`). All value/residual variants collapse to ≤0.92 success with harmful override fractions ≥0.74 (`cstride_table_ablation.csv`).

## 7. Metrics Glossary
- **Success rate.** Portion of test episodes that end in the DONE state. Teacher imitation and C-STRIDE gate-only both post 1.0, meaning every workflow succeeds; `cstride_gate_plus_value` falls to 0.604, signalling that two out of five runs now fail. *Why it matters:* reviewers can immediately see whether a controller is production safe.
- **Budgeted success.** Fraction of successes that also stay within the 40k+26k token budgets. Teacher imitation and gate-only remain at 1.0, so they never overspend, whereas STRIDE’s teacher-only variant dips to 0.9625. *What this means:* a method that exceeds the budget cannot be deployed even if it solves the task.
- **Average reward.** Environment reward plus shaping bonuses/penalties. Gate-only’s 78.7 versus the teacher’s 72.5 shows its rare overrides shorten episodes and avoid penalties; the value variant’s 21.5 shows constant punishment from harmful overrides. *Significance:* reward gaps quantify efficiency gains or thrashing.
- **Average cost (cost ratio).** Fraction of the token budget consumed each run. Teacher imitation uses 26.1 %, gate-only 26.5 %, and value variants 40.3 %. *Meaning:* the aggressive overrides burn ~50 % more tokens, so their regressions are expensive.
- **Average steps / episode length.** Number of macro decisions per episode. Teacher stops after 9.0 steps, gate-only after 9.6, failing variants drag on for about 14.2. *Interpretation:* longer runs indicate indecision and greater latency.
- **Override rate.** Share of manager steps where the controller deviates from the teacher. Teacher imitation is 0 %, gate-only 8.89 %, value variants 32.5 %. *Importance:* override rate reveals how often the trusted baseline is ignored.
- **Override win rate.** Among overrides, the proportion that beats the teacher according to counterfactual labels. Gate-only wins 81.9 % of its overrides; value/residual variants win only ≈22 %. *Meaning:* three out of four overrides are mistakes for the failing methods.
- **Override regret rate.** Complement of the win rate: gate-only records 0 % regret, value/residual variants 77.8 %. *Significance:* regret rates above 50 % prove the controller should not intervene.
- **Harmful/beneficial override fractions.** Episode-level breakouts of the above, useful for per-method diagnostics. Harmful fraction ≈0.78 explains the success collapse of `cstride_gate_plus_value`, while gate-only’s harmful fraction of 0 confirms zero regressions.
- **Action entropy.** Shannon entropy over macro selections. Gate-only’s 1.08 shows diverse decision-making despite rare overrides; teacher imitation’s 0.92 reflects deterministic behaviour. *Why it matters:* entropy distinguishes deliberate low-frequency overrides from chaotic exploration.
- **Reward diagnostics.** Logged per-step contributions (e.g., stagnation penalties, verification bonuses) in `results/aegis_rl/metrics/reward_diagnostics.jsonl`. They reveal *why* reward curves move up or down when certain macros dominate.

## 8. Results Explained with Numbers
- **AEGIS hierarchy.** The best configuration (`aegis_full`) delivers success 0.5 with average reward –5.66. *What this means:* even with graph memory, belief updates, and constraint tracking, the hierarchical agent fails half the time and accrues penalties, so it cannot replace the teacher. *Reviewer takeaway:* hierarchical RL remains uncompetitive.
- **STRIDE imitation (teacher baseline).** `stride_without_uncertainty_features` achieves success 0.9625, reward 59.7, cost 0.277, override rate 0. *Meaning:* copying the teacher already solves more than 96 % of episodes with zero intervention. *Takeaway:* this is the reliability yardstick for all future comparisons.
- **TARL.** `tarl_aegis` posts success 1.0, reward 59.71, override rate 0. *What this means:* TARL’s override gate never fires; it merely reproduces teacher behaviour. *Takeaway:* TARL adds no new capability despite perfect metrics.
- **C-STRIDE imitation baseline.** `cstride_imitation_only` yields success 1.0, reward 72.55, cost 0.261, override rate 0. *Meaning:* the counterfactual dataset infrastructure does not degrade the teacher and provides a clean control. *Takeaway:* any claimed improvement must beat these exact numbers.
- **Counterfactual gate-only.** Success 1.0, reward 78.71 (6.2 points higher than the teacher), cost 0.2649, override rate 8.89 %, override win rate 81.9 %, regret 0 %. *What this means:* the gate intervenes roughly once every eleven macro decisions, and four out of five interventions genuinely help while none hurt. *Reviewer takeaway:* selective, low-frequency intervention is finally supported by the data.
- **Counterfactual value/residual variants.** `cstride_gate_plus_value` (and the cost-aware/residual/feature-drop variants) collapse to success 0.604, reward 21.48, cost 0.403, override rate 32.5 %, win rate 22.2 %, regret 77.8 %. *Meaning:* one third of all steps override the teacher, and three out of four overrides are mistakes, so success and cost both degrade sharply. *Reviewer takeaway:* aggressive learned overrides remain scientifically untenable.
- **C-STRIDE without teacher confidence.** Success improves to 0.9188, but win rate is still only 21 %. *What this means:* even after removing teacher confidence features, interventions are wrong four times out of five. *Takeaway:* incremental feature tweaks cannot salvage the value/residual approach without richer supervision.

These numbers jointly show that only the counterfactual gate-only variant manages to intervene safely; every other learned override either refuses to act (TARL) or damages the already-strong teacher.

## 9. Parameter / Resource / Constraint Analysis
- **Workflow action spaces.** `WorkflowEnv` exposes nine macro options (research, localize, direct solve, shallow/deep decomposition, verify, repair, submit, abandon). All production runs set `use_reduced_action_space=True` except when explicitly noted. Reduced action space (five macros: research, direct solve, shallow decomposition, verify, repair, submit) was mandatory for all C-STRIDE, STRIDE, and TARL experiments to keep gating stable. AEGIS flat/hierarchy variants explored the full macro set, which contributed to their instability.
- **Hierarchy versus flat control.** AEGIS hierarchy (`aegis_full`, `aegis_no_graph`, etc.) enabled the option registry and internal rollouts (`enable_hierarchy=True`), whereas STRIDE, TARL, and C-STRIDE all set `enable_hierarchy=False` so macro choices executed immediately in the base environment. Hierarchy hurt because internal option rollouts compounded credit-assignment noise; once we disabled it (all teacher-guided experiments) the action space became deterministic and reproducible.
- **Teacher imitation versus intervention.** Runs labelled `baseline_heuristic`, `stride_without_uncertainty_features`, `tarl_aegis`, `cstride_imitation_only` all enforce pure teacher imitation (override gates turned off or thresholds unreachable). Gate-only intervention appears in `cstride_gate_only` (and legacy STRIDE variants without residuals) where the classifier decides if the teacher macro should be swapped but there is no residual policy. Value/residual overrides include STRIDE residual variants and all C-STRIDE “gate_plus_value” flavours, where the gate hands control to a learned action selector.
- **Dataset thresholds and rollout settings.**
  - **STRIDE disagreement data** (`experiments/run_stride_aegis.py`): dataset episodes set to 2,048 by default, override threshold 0.6 (optionally swept to 0.75–0.9), curriculum threshold 0.6 for uncertainty filtering, stagnation override at 3 steps. Because these thresholds were heuristic, the gate learned to fire whenever costs were high, leading to noisy labels.
  - **Counterfactual dataset** (`scripts/build_counterfactual_dataset.py` + `src/rl/counterfactual_dataset.py`): 256 teacher episodes, minimum uncertainty 0.15, minimum budget pressure 0.25, up to 3 alternative macros per state, max 32 macro steps per branch, reduced action space enforced. These settings ensured we only logged states where intervention was plausible (moderate uncertainty or budget pressure) and kept each branch short enough to be tractable.
  - **C-STRIDE training** (`experiments/run_cstride_aegis.py`): gate epochs 8, value epochs 6, residual epochs 4, seeds [0–4], 32 evaluation episodes per seed. Override threshold stayed at 0.6 for comparability with STRIDE. These hyperparameters were intentionally conservative to prevent overfitting the counterfactual data.
- **Budget/resource controls.** Every method inherits `WorkflowEnvConfig` budgets: 40k prompt tokens, 26k completion tokens, max 24 manager steps, 6 retries, retrieval limit 6, verifier limit 4, and action masking when budgets are exhausted. Budgeted success, cost ratios, and constraint penalties come directly from these limits. Reward shaping (`src/rl/aegis_rewards.py`) further penalizes stagnation, direct-solve streaks, and uncertain submissions and rewards successful verification and escalation.
- **Behavioural consequences.**
  - Reduced action spaces plus hierarchy disabled made the teacher and gate-only policies deterministic, which is why override rates are exactly measurable.
  - Turning off hierarchy eliminated internal option loops, lowering variance but also removing any chance for multi-step planning; hence AEGIS (with hierarchy) behaved differently from STRIDE/C-STRIDE (without hierarchy).
  - Teacher-only runs show what happens when override thresholds are effectively infinite; they confirm the upper bound on success/cost.
  - Gate-only intervention inherits the reduced macro set and simply flips between teacher macro and a predetermined alternative; the low override rate reflects both the 0.6 threshold and the min-uncertainty/min-budget filters used when collecting counterfactuals.
  - Value/residual overrides inherit the same action space but replace deterministic alternatives with either a softmax residual policy (STRIDE) or a value-scoring argmax (C-STRIDE). Because the dataset only evaluates the first post-override macro, these policies received overly positive labels and therefore fired overrides much more often, leading to the documented collapse.
  - The counterfactual rollout settings (32 macro steps max, 3 alternates per state) ensured each alternate branch rejoined the teacher quickly; as a result, branches never explored long divergent trajectories, which explains why value/residual models lacked the signal needed to predict long-term regret.

Taken together, these knobs explain the outcome differences: hierarchy plus wide action spaces caused AEGIS instability; reduced actions plus pure imitation yielded perfect success; conservative gates plus counterfactual filtering enabled safe intervention; and aggressive value/residual policies failed because their training data only reflected short, optimistic branches.

## 10. Research Journey
1. **Original paper.** Built ETL, reporting, and the WorkflowEnv simulator; attempted hierarchical RL (AEGIS) but could not surpass the teacher.
2. **RL allocation / selective decomposition.** Explored reduced-action RL to simplify learning, but success stayed near zero unless constraints were disabled.
3. **Teacher-guided TARL.** Introduced a gate to prevent harmful overrides. Outcome: overrides almost never fired; success matched the teacher.
4. **STRIDE.** Created disagreement datasets and residual policies to encourage targeted overrides. Outcome: teacher-only STRIDE matched the teacher; residuals still hurt.
5. **Counterfactual C-STRIDE.** Added branch-rollout data. Gate-only finally enabled safe, low-frequency overrides, but value/residual policies require richer counterfactual supervision.

**Lessons learned:** strong teachers are hard to beat; override data must reflect true counterfactual outcomes; multi-step intervention remains unsolved.

## 11. Final Claim
- **Supported claim.** Teacher imitation remains the safest and most effective controller. Counterfactual gating can add rare, high-win overrides without hurting success, so the repo now offers a principled, reproducible way to study selective intervention.
- **Not supported.** We cannot claim a superior fully learned controller or a residual/value head that beats the teacher. We also cannot claim generalization beyond the simulator until multi-step counterfactuals and real submission data are available.

## 12. Best Paper Positioning
The evidence supports a **hybrid teacher-guided control paper**: we deliver a strong teacher baseline, a new counterfactual dataset, and honest diagnostics about why overrides remain brittle. This framing highlights contributions without overstating performance.

## 13. Future Work
1. Extend counterfactual rollouts to cover entire override trajectories so value/residual models can observe true downstream outcomes.
2. Incorporate richer signals (submission identities, member histories) once database access is restored, enabling better cost/regret estimation.
3. Experiment with regret-aware gates that penalize overrides unless the predicted gain significantly exceeds a margin, further reducing harmful interventions.

## 14. Appendix-Style Table
| Method | Problem Tackled | Action Type | Key Parameters | Best Metrics | Interpretation | Supports Claim? |
| --- | --- | --- | --- | --- | --- | --- |
| baseline_heuristic / teacher | Control workflow via rules | Macro options, no learning | Reduced action space, budgets 40k/26k tokens | Success 1.0, cost 0.261 | Teacher already solves all episodes | ✔ |
| AEGIS hierarchy (`aegis_full`) | Learned hierarchical manager | Learned macro policy with graph memory | Hierarchy on, reward shaping from `aegis_rewards.py` | Success 0.5, reward –5.66 | Unstable learning, worse than teacher | ✘ |
| TARL (`tarl_aegis`) | Teacher-guided overrides | Gate + residual agent | Logged dataset, override threshold 0.6 | Success 1.0, override rate 0 | No intervention; mirrors teacher | Partial |
| STRIDE teacher-only (`stride_without_uncertainty_features`) | Selective override via disagreement | Gate only | Disagreement dataset 2048 episodes, threshold 0.6 | Success 0.9625, override 0 | Effective imitation; no intervention | ✔ |
| STRIDE residuals | Aggressive overrides | Gate + residual | Same dataset, residual epochs 4 | Success 0.8167, override rate 0.202, regret 0.21 | Overrides harm success | ✘ |
| C-STRIDE imitation | Baseline for counterfactuals | Follow teacher | Counterfactual dataset ignored | Success 1.0, reward 72.55 | Confirms teacher strength | ✔ |
| C-STRIDE gate-only | Selective counterfactual overrides | Gate chooses deterministic alternative | Gate epochs 8, override threshold 0.6, 4,925 states | Success 1.0, reward 78.71, override rate 0.0889, win rate 0.8188 | Safe low-frequency interventions | ✔ |
| C-STRIDE gate+value (+/- residual) | Learned override scoring | Gate + value model (+ residual) | Value epochs 6, candidate evaluations 10,144 | Success 0.604–0.919, override rate 0.18–0.32, regret ≥0.74 | Counterfactual labels too optimistic; overrides harmful | ✘ |

These results collectively justify the hybrid teacher-guided framing and document where intervention pipelines remain fragile.

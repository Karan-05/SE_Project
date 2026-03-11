# Metrics Glossary for AEGIS / STRIDE / C-STRIDE

| Metric | Definition | Interpretation | Example Values |
| --- | --- | --- | --- |
| Success rate | Fraction of evaluation episodes that reach the simulator’s DONE state | Measures reliability of the workflow controller; 1.0 means every run solved the task | Teacher imitation: 1.0; C-STRIDE gate-only: 1.0; `cstride_gate_plus_value`: 0.604 |
| Budgeted success | Success rate conditioned on staying within prompt+completion token budgets (40k + 26k) | Shows whether wins respect resource constraints | Teacher imitation & gate-only: 1.0; STRIDE teacher-only: 0.9625 |
| Average reward | Mean shaped reward per episode (env reward + bonuses/penalties from `aegis_rewards.py`) | Captures efficiency: higher reward reflects faster progress, fewer penalties | `cstride_gate_only`: 78.71; teacher imitation: 72.55; failing value variant: 21.48 |
B Avg cost (cost ratio) | Fraction of prompt+completion budget consumed | Lower is better; indicates budget headroom | Teacher imitation: 0.261; STRIDE teacher-only: 0.277; failing variants: ≈0.403 |
| Average steps | Mean number of macro decisions per episode | Measures episode length and latency | Teacher imitation: 9.0; gate-only: 9.6; value variants: 14.2 |
| Override rate | Portion of manager decisions where the policy deviates from the teacher | Quantifies intervention frequency; 0 means pure imitation | Gate-only: 0.0889 (8.9 % of steps); value variants: 0.324 |
| Override win rate | Fraction of overrides where the counterfactual label indicates a better outcome | Evaluates intervention quality; >0.5 means overrides help more than hurt | Gate-only: 0.81875; value variants: 0.222; STRIDE residuals: 0.174 |
| Override regret rate | Fraction of overrides flagged as worse than teacher | Highlights harmful interventions | Gate-only: 0.0; value variants: 0.778; STRIDE residuals: 0.210 |
| Harmful override fraction | Same as regret rate but logged per-method in `stride_metrics.csv` | Helps compare across variants with different override counts | Gate-only: 0.0; value variants: 0.778 |
| Beneficial override fraction | Portion of overrides that improved reward/cost deltas | Complements win rate | Gate-only: 0.819; value variants: 0.222 |
| Action entropy | Entropy of macro-action histogram | Measures diversity: low entropy implies deterministic behaviour | Teacher imitation: 0.916; gate-only: 1.081; value variants: 0.975 |
| Average tokens (WorkflowEnv) | Prompt/completion tokens spent per episode (reported in AEGIS tables) | Indicates raw resource use, complements cost ratio | `aegis_full`: 23.2k prompt + cost ratio 0.085; baseline heuristics: 21.4k |
| Constraint penalty | Snapshot from `ConstraintTracker` summarizing budget/latency violations | Used in reward shaping; lower values mean the controller stayed within constraints | Not directly tabulated, but informs `avg_constraint` in `table_main.csv` |

**How to use the glossary:** interpret every performance claim through the lens of these metrics. A method can only be considered an improvement if it (a) keeps success and budgeted success high, (b) reduces cost or steps, and (c) if it overrides, maintains a win rate far above the regret rate.

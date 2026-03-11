# ASE 2026 Workflow RL Notes

## Proposed Title
Trace-Aware Workflow Reinforcement Learning for Agentic Software Engineering

## Novelty Statement
We shift RL control from task selection to budget-aware decision making over Planner–Solver–Verifier workflows with explicit uncertainty and trace supervision.

## Research Questions
1. Can a single policy learn to navigate decomposition, retrieval, solving, verification, and repair under strict budgets?
2. How do uncertainty signals (verifier disagreement, failure counters) influence control effectiveness?
3. What is the marginal utility of verifier, retrieval, and deep decomposition actions when budgets are constrained?

## Code ↔ Paper Mapping
- `src/rl/workflow_env.py` → Environment and methodology section describing simulator assumptions and reward design.
- `src/rl/workflow_agents.py` → Agent architecture section.
- `experiments/run_workflow_rl.py` → Experimental setup and evaluation protocol.
- `reports/ase2026_workflow_rl/summary.md` → Empirical findings.
- `reports/ase2026_workflow_rl/figure_*.png` → Quantitative results figures.
- `reports/ase2026_workflow_rl/table_*.csv` → Tabulated metrics for main and ablation studies.

## Figures/Tables for Paper
- `figure_success_vs_cost.png`, `figure_budgeted_success.png`, `figure_action_distribution.png`, `figure_ablation.png`
- `table_main.csv`, `table_ablation.csv`

## Limitations and Threats to Validity
- Environment relies on stylized dynamics rather than live coding tasks.
- Token costs approximate LLM usage; real deployment may have different scaling.
- Policies trained with few episodes in quick sweeps may require longer training for stable convergence.
- Ablation toggles are deterministic and may not capture partial degradations observed in practice.

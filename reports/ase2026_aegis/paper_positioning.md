# Paper Positioning

## Thesis
1. **Infrastructure contribution** – Release the reproducible Topcoder ETL audit plus refreshed artefacts (`analysis/output/*.csv`, `data/raw`, `data/processed`) so reviewers can rebuild the 22,023-challenge corpus end-to-end.
2. **Counterfactual supervision** – Introduce the branch-rollout dataset builder and show how the resulting `results/aegis_rl/counterfactual` artefacts support offline override gating/value experiments.
3. **Control-method finding** – Demonstrate that imitation still dominates: the counterfactual gate-only hybrid matches teacher success while firing rare, high-win overrides, but every value/residual head remains harmful. The honest story is a hybrid/negative-result paper, not a flagship override.
4. **Real-repo instrumentation** – Ship the multi-file prompt-tuning loop (`scripts/run_prompt_tuning_iteration.py`) plus the repo harness upgrades (snapshot verification, edit-shape metrics) that expose why learned repairs still fail on the Topcoder SRM backlog. The story is semantic under-editing, not plumbing.

## Narrative Arc
- **Section 1 – Data pipeline**: Downloader → JSON normalisation → MySQL schema → export stack, plus the new counterfactual dataset export.
- **Section 2 – Dataset insights**: `analysis/output/report.md` stats (22k challenges, prize pools, AI tags) and the remaining gaps (registrant coverage, submissions data).
- **Section 3 – Experimental setup**: `WorkflowEnv`, teacher baselines, STRIDE/TARL, and the new C-STRIDE loop (`scripts/build_counterfactual_dataset.py`, `experiments/run_cstride_aegis.py`).
- **Section 4 – Results**: Compare teacher vs. counterfactual gate-only vs. failing overrides using `reports/ase2026_aegis/{table_main,cstride_table_main,cstride_table_ablation}.csv` plus per-variant summaries in `results/aegis_rl/cstride_*`, and close with the real-repo diagnostics from `reports/decomposition/real_world/real_repo/summary.md` (OpenAI run, localization precision 1.0 but contract coverage 0.38–0.67, semantic failures dominated by aggregation/filtering) to show the semantic wall the LLM agents still hit.
- **Section 5 – Discussion**: Diagnose why overrides fail (short counterfactual rollouts, value heads that over-fire, lack of submissions data) and outline the next experiments (longer branch rollouts, richer disagreement logging, registrant refresh).

## Position vs. Prior Work
- **Unique asset** – We combine a transparent ETL audit with a shareable counterfactual override dataset, something prior ASE corpora lack.
- **Method honesty** – We state plainly that the teacher remains the main method; counterfactual gating is diagnostic, and the negative results around value/residual overrides are part of the contribution.

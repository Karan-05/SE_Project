# Threats to Validity

1. **Synthetic environment fidelity** – All RL experiments run inside the scripted `WorkflowEnv`; we do not yet execute LLM agents on real Topcoder tasks, so any gains/losses are simulator-dependent.
2. **Incomplete registrant/submission data** – Without a `TOPCODER_BEARER_TOKEN`, submissions and registrant tables stay sparse (`snapshots/Challenge_Member_Mapping.csv`), limiting the realism of downstream worker models and reward shaping.
3. **Counterfactual coverage** – The new dataset logs only the first macro of each override branch before handing control back to the teacher. Value/residual heads therefore overestimate the benefit of “do anything else,” which explains why they over-fire and fail (Section `cstride_failure_analysis.md`).
4. **MySQL unavailability** – In this sandbox we rely on exported CSV/JSON snapshots; we cannot re-run the MySQL ETL (blocked by docker socket permissions), so we assume the schema dumps remain authoritative.
5. **Limited seeds / episodes for some baselines** – Hierarchical AEGIS and TARL sweeps reuse historic runs; only STRIDE/C-STRIDE were re-run with 5 seeds × 32 episodes. While the trends are clear, fresh AEGIS/TARL sweeps would further reduce statistical noise.

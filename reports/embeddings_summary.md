# Embedding Impact

Node2Vec-style representations trained over the worker↔task graph provide consistent classification gains on the held-out split:

- **Failed/No Winner** climbs from F1 0.91 → **0.98** (+0.068), enabling early flagging of challenged markets.
- **Starved/Dropped** jumps from F1 0.964 → **0.988** (+0.024), reducing missed zero-submission events.
- **Has Winner** improves slightly (F1 0.986 → **0.995**, +0.009) by injecting structural context on successful pairings.

See `reports/tables/embeddings_ablation.csv` for the detailed per-model metrics.

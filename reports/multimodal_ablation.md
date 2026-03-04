# Multimodal Ablations

Latest logistic-regression comparisons (test split):

- **Starved/Dropped**: text+time F1 0.910 → multimodal ( +embeddings + metadata ) **0.982**.
- **Failed**: F1 0.917 → **0.952** when adding structured and market context.
- **Has Winner**: already high at F1 0.986; multimodal edges it to 0.9865 by stabilising precision.

To populate the full table (including text-only / metadata-only variants and tree models), run:

```
python train_supervised.py --ablation
```

The command writes `reports/tables/multimodal_ablation.csv`, which `paper/main.tex` will auto-include.

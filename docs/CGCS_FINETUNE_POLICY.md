# CGCS Fine-tuning Policy

1. **Source data** – Only successful CGCS attempts with valid JSON payloads are eligible. Pull the latest stats from `data/cgcs/*.jsonl` and `openai_artifacts/normalized`.
2. **Filtering** – Apply the following gates inside `scripts/openai_ops/prepare_finetune_data.py`:
   - pass grader checks (clause discharge + schema compliance)
   - no forbidden edit paths (see `skills/cgcs_constraints.json`)
   - witness density ≥ 1 per clause
   - exclude held-out tasks listed in `configs/openai_ops/research.yaml`
3. **Splitting** – Deterministically assign rows to `data/cgcs_finetune/train.jsonl` and `data/cgcs_finetune/valid.jsonl`. Enforce no overlapping `task_id`s.
4. **Leakage checks** – Verify that held-out Topcoder tasks never appear in training and that train/valid share no tasks. Emit warnings in the stats JSON.
5. **Job submission** – Run `scripts/openai_ops/start_finetune.py` only when:
   - train set ≥ 50 examples
   - valid set ≥ 10 examples
   - leakage warnings list is empty
6. **Audit trail** – Every fine-tune job writes metadata to `openai_artifacts/fine_tunes/{timestamp}.json` (dataset hashes, counts, job IDs). Reference these files in papers or artifact submissions.

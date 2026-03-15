# CGCS Evaluation Protocol

1. **Dataset** – Base eval items on `data/cgcs/{split}.jsonl`. Each row captures clause state, witnesses, regression guards, and the raw edit payload from the on-prem benchmark.
2. **Item builder** – Use `scripts/openai_ops/build_eval_items.py --split <split>` to create deterministic JSONL inputs for open-book evaluation. Control sample size with `--max-items` and `--seed`.
3. **Batch requests** – Convert eval items into `/v1/responses` requests via `scripts/openai_ops/build_batch_requests.py`. Each request includes:
   - system prompt describing clause focus
   - user context (contract items, witnesses, guards)
   - strict JSON output schema for edit payloads
4. **Submission** – Upload request JSONL and start a Batch job with `scripts/openai_ops/submit_batch.py`. Persist metadata in `openai_artifacts/batches`.
5. **Polling & normalization** – Run `scripts/openai_ops/poll_batch.py --batch-id <id>` until completion. It stores raw outputs, normalized JSONL, and a summary CSV in `openai_artifacts/normalized`.
6. **Grading** – Execute `scripts/openai_ops/run_graders.py --batch-id <id>` to evaluate clause discharge, regression handling, witness usage, payload schema compliance, and unnecessary edits. Results land in `openai_artifacts/graders/{run_id}.{json,csv}`.
7. **Reporting** – Stats from the grading run feed ASE tables/figures and should be referenced in `reports/ase2026_aegis`.

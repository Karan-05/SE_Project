# CGCS Dataset Schema

The Contract-Graph Counterexample Satisfaction (CGCS) dataset captures every repair attempt executed on the Topcoder real-repo benchmark. Each record is serialized as a single JSON object and stored in `data/cgcs/{train,dev,test}.jsonl`.

## File layout

- `train.jsonl`, `dev.jsonl`, `test.jsonl`: deterministic split produced by `scripts/build_cgcs_dataset.py`.
- Each line is a UTF-8 JSON object representing one attempt (initial or repair round).

## Field reference

| Field | Type | Description |
| --- | --- | --- |
| `task_id` | `str` | Canonical Topcoder repo task identifier. |
| `strategy` | `str` | Decomposition strategy used for the attempt (e.g., `cgcs`). |
| `round_index` | `int` | Zero-based attempt index inside the agentic loop. |
| `repo_snapshot_sha256` | `str` | SHA-256 fingerprint of the repo snapshot verified before executing the attempt. |
| `contract_items` | `dict` | Snapshot of the strategy plan’s contract payload (category, description, and clause mapping). |
| `active_clause_id` | `str` | CGCS clause selected for the attempt (`""` if inactive). |
| `regression_guard_ids` | `list[str]` | Clause identifiers that must not regress (fully satisfied in prior rounds). |
| `witnesses` | `list[dict]` | Linked semantic witnesses driving the clause (see `src/decomposition/real_repo/witnesses.py`). |
| `candidate_files` | `list[str]` | Candidate implementation files from the decomposition plan. |
| `context_snippets` | `list[str or dict]` | Optional snippets shared with the model (often empty for Topcoder). |
| `raw_edit_payload` | `str` | Raw JSON edit proposal returned by the LLM. |
| `outcome_metrics` | `dict` | Minimal attempt diagnostics (`status`, `pass_rate`, `duration`, `failing_tests`, `error_types`). |
| `oracle_patch_present` | `bool` | Indicates whether the oracle/teacher patch is available for the task. |

## Generation process

1. **Trace parsing** – `scripts/build_cgcs_dataset.py` walks `reports/decomposition/traces/<strategy>/<task>.json` to collect CGCS state, clause witnesses, and round metadata.
2. **Run logs** – raw edit payloads and repo snapshot hashes are sourced from `reports/decomposition/real_world/real_repo/runs/<task>/<strategy>/logs`.
3. **Splitting** – Records are deterministically assigned to `train/dev/test` by hashing `task_id:strategy`.

Run the builder:

```bash
python scripts/build_cgcs_dataset.py \
  --run-root reports/decomposition/real_world/real_repo/runs \
  --trace-root reports/decomposition/traces \
  --output-dir data/cgcs
```

## Anonymization

Use `scripts/anonymize_artifact.py` to produce a scrubbed copy of the dataset that redacts `raw_edit_payload` and replaces `task_id` with a deterministic hash.

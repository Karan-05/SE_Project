# Pipeline Debugging Guide

This note collects the recurring issues that caused "empty" CGCS rows and hollow batch artifacts, the fixes in this repo, and the workflows to validate future scaling runs.

## Why dataset rows were empty

1. **Fragile field extraction** – the original builder only looked at `plan.contract`, `cgcs_state.active_clause`, a single witness array, and `metadata.raw_payload`. When traces contained alternate shapes (legacy contract snapshots, witness samples on the round object, raw payloads stored as `response_text`, etc.) the builder silently emitted blanks.
2. **Unfiltered candidate lists** – everything under `candidate_files` (including `node_modules`, lockfiles, and test fixtures) was piped to evaluation. Downstream agents wasted tokens on junk.
3. **No validation or rejection accounting** – unusable rows (missing clause id + payload) were mixed into train/dev/test, so later scripts could not separate "bad source data" from "agent failure".

### Fixes

* `scripts/build_cgcs_dataset.py` now uses a typed schema, resilient extraction helpers, and row-level validation with `row_quality` diagnostics and `row_errors`.
* Contract items fall back across `round.edit_metadata.cgcs_state.contract_items`, `trace.metadata.contract`, and legacy plan contracts; placeholders like `{"inputs": "Underspecified"}` are flagged `contract_quality="weak"` and rejected unless `--allow-placeholder-contracts` is passed.
* `active_clause_id` is inferred across every `cgcs_state` variant (and, failing that, linked witness ids), and missing values are recorded explicitly.
* Witnesses merge structured samples with log-file parsing (deduped by signature), while raw payloads check `metadata.raw_payload`, `response_text`, `model_output`, and finally the on-disk log text.
* Candidate files are filtered (tests and dependency folders are stripped unless `--include-tests`), and every row is tagged with its provenance (`source_paths`) plus per-field quality notes.
* `rejected.jsonl` + `dataset_summary.json` expose unusable rows and the reasons (`missing_active_clause_id`, `empty_contract_items`, `missing_witness_and_payload`, etc.), while `debug_dataset_quality.py` prints coverage stats and sample failures.

## Field sourcing cheat sheet

| Field | Primary sources | Secondary/fallbacks |
| --- | --- | --- |
| `contract_items` | `round.edit_metadata.cgcs_state.contract_items`, `round.edit_metadata.contract_items` | `trace.metadata.contract`, `trace.plan.contract_items`, `trace.contract` |
| `active_clause_id` | `cgcs_state.active_clause_id`, `cgcs_state.active_clause`, `round.active_clause_id` | First witness `linked_contract_ids`, logged witness samples |
| `witnesses` | `cgcs_state.witness_sample(s)`, `round.witness_samples` | Parsed from `logs/tests_*_roundN.log` (extracts message, category, file/line) |
| `raw_edit_payload` | `log.metadata.raw_payload`, `log.raw_payload`, `log.response_text`, `log.model_output` | Entire `edits_roundN.json` file contents |

## Responses API gotcha

The Batches "Responses" endpoint does **not** honour `response_format` (that is a Chat-Completions field). Structured outputs must be requested through `text.format`:

```json
"text": {
  "format": {
    "type": "json_schema",
    "name": "cgcs_repo_patch",
    "schema": {...},
    "strict": true
  }
}
```

If you send `response_format`, OpenAI silently ignores the schema, returns free-form text, and the normalizer cannot parse edits.

## Understanding batch artifacts

* Every batch emits up to **two files**: `output_file_id` (success rows) and `error_file_id` (per-request failures). If only the error file exists, the run failed and `summary.success_count` will be zero – do not treat that as a success.
* `scripts/openai_ops/poll_batch.py` now downloads both files, writes:
  * `{batch_id}_raw_success.jsonl` and `{batch_id}_raw_errors.jsonl`
  * Normalized success rows (`{batch_id}.jsonl`) and normalized errors (`{batch_id}_errors.jsonl`)
  * CSV/JSON summaries capturing `success_count`, `error_count`, `malformed_json_count`, top error codes, and file ids.
* The normalized success rows include:
  * `response_id`, `response_status`, `output_text`, `parsed_object` (if JSON parsing succeeded), `parsing_error`, `usage_tokens`, and `malformed_json` flags.
* The normalized error rows retain the original payload plus `error_code` and `error_message`. Use `scripts/openai_ops/debug_batch_errors.py` to group them by root cause.

## Scaling to the 22k Topcoder corpus

Not every challenge is runnable or even has an accessible repo. The new tooling isolates the executable subset before attempting the CGCS pipeline.

1. **Index the corpus**  
   ```
   python scripts/topcoder/build_corpus_index.py \
     --tasks-csv data/raw/tasks.csv \
     --legacy-pages 'challenge_data/**/*.json.gz'
   ```
   This script normalizes task metadata + legacy JSON exports into `data/topcoder/corpus_index.jsonl` (and `*.parquet` when pandas/pyarrow is installed), tagging each challenge with `has_repo`, `has_tests`, `likely_executable`, technologies, and tags.

2. **Filter to runnable repos**  
   ```
   python scripts/topcoder/select_executable_subset.py \
     --index-file data/topcoder/corpus_index.jsonl \
     --output data/topcoder/executable_subset.jsonl
   ```
   The selector keeps challenges that (a) link to a repo, (b) mention tests/tooling, (c) sit on Development/QA tracks, (d) are not duplicates (one repo per challenge), and (e) meet the minimum submission threshold.

3. **Apply CGCS repair only to the executable subset** – running CGCS across all ~22k challenges wastes tokens on prompts without repos/tests. Use the corpus index for retrieval/mining and restrict end-to-end repair/agent benchmarks to `executable_subset.jsonl`.

4. **Diagnose datasets/batches early** – run `debug_dataset_quality.py` after each rebuild, inspect `batch_request_summary.json` for skip reasons (weak contracts, missing witnesses) and poll batches with the new poller to surface real API failures immediately.

5. **Publish the funnel snapshot** – `python scripts/topcoder/build_funnel_report.py` aggregates every stage into `data/topcoder/funnel_report.json` and `reports/ase2026_aegis/funnel_snapshot.md`, so you can cite live counts for raw corpus (22,023), likely executable (16,562), selected repos (3,966), CGCS rows (60), eval items (9), batch requests/successes, and solved tasks. The same run also surfaces the top CGCS rejection reasons and batch error codes.

With these guardrails the pipeline fails loudly, surfaces missing credentials/data, and is ready for larger Topcoder runs.

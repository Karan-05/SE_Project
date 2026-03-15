# OpenAI Batch Workflow

This document captures the supported Responses Batch workflow from CGCS rows to normalized outputs and highlights where each artifact is written.

## 1. Build eval items

```
python scripts/openai_ops/build_eval_items.py \
  --input-dir data/cgcs \
  --split test \
  --output-file openai_artifacts/eval_items_test.jsonl \
  --max-items 128
```

* Reads `data/cgcs/{train,dev,test}.jsonl` and emits structured rows (`task_id`, `strategy`, `active_clause_id`, witnesses, payloads) in `openai_artifacts/eval_items_<split>.jsonl`.
* Deterministic shuffling is controlled via `--seed`.
* If the source dataset has zero usable rows (current strict build: 60 rejected rows), the output will be empty—check `data/cgcs/dataset_summary.json` before running this stage.

## 2. Build batch requests

```
python scripts/openai_ops/build_batch_requests.py \
  --eval-items openai_artifacts/eval_items_test.jsonl \
  --output openai_artifacts/batch_requests.jsonl \
  --skipped-output openai_artifacts/skipped_eval_items.jsonl \
  --summary-output openai_artifacts/batch_request_summary.json \
  --seed 7
```

* Each eval item is wrapped in a Responses API call that uses the new `text.format` JSON-schema interface:

```json
{
  "model": "gpt-4.1-mini",
  "input": [...],
  "text": {
    "format": {
      "type": "json_schema",
      "name": "cgcs_repo_patch",
      "schema": {...},
      "strict": true
    }
  },
  "store": false
}
```

* Rows missing an active clause, witnesses/payloads, or exhibiting weak contracts are skipped; reasons are recorded in `openai_artifacts/skipped_eval_items.jsonl`, and counts live in `batch_request_summary.json`.
* Custom IDs follow the `{task_id}-{strategy}-{round_index}-{seed}` pattern and are mirrored in the metadata for downstream normalization.

## 3. Submit a batch

```
python scripts/openai_ops/submit_batch.py \
  --requests-file openai_artifacts/batch_requests.jsonl \
  --output-dir openai_artifacts/batches
```

* Uploads the request JSONL as an OpenAI file and starts a `/v1/responses` batch.
* Records `batch_id`, `input_file_id`, and request counts in `openai_artifacts/batches/<timestamp>.json` plus a convenience symlink `batches/latest.json`.
* If `OPENAI_API_KEY` is missing the script writes a placeholder metadata file instead of crashing.

## 4. Poll, normalize, and summarize

```
python scripts/openai_ops/poll_batch.py --latest
```

* Polls the `batch_id` stored in `openai_artifacts/batches/latest.json`.
* Downloads both the success file (`*_raw_success.jsonl`) and error file (`*_raw_errors.jsonl`) whenever present.
* Normalizes success rows into `openai_artifacts/normalized/<batch_id>.jsonl` with fields:
  * `payload` – parsed JSON from the model (or empty when malformed).
  * `parsed_object` / `parsing_error` / `malformed_json` – so malformed outputs are counted explicitly.
  * `metadata.task_id`, `strategy`, `clause_id`, and usage tokens.
* Normalized errors are written to `<batch_id>_errors.jsonl` and grouped by `error_code`.
* CSV/JSON summaries (`<batch_id>_summary.csv` / `json`) capture counts, average output tokens, and the top error codes. Convenience links `openai_artifacts/normalized/latest*.{jsonl,csv}` are updated automatically.

## 5. Debug errors and dataset quality

* `python scripts/openai_ops/debug_dataset_quality.py --input-dir data/cgcs` – prints active clause coverage, witness/payload ratios, and the top rejection reasons in `data/cgcs/rejected.jsonl`.
* `python scripts/openai_ops/debug_batch_errors.py --errors-file openai_artifacts/normalized/latest_errors.jsonl` – groups API failures by code and lists the affected `custom_id`s.

Together these scripts provide an auditable path from CGCS rows to OpenAI batch outputs while failing loudly whenever the inputs are weak or the API returns malformed responses.

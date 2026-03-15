# CGCS Runtime Trace Contract

Strict dataset building depends on deterministic, machine-readable runtime traces. Every CGCS repair round must therefore emit a consistent metadata payload so that `scripts/build_cgcs_dataset.py --strict` can recover usable rows.

## Required Per-Round Fields

Each entry in `round_entry.edit_metadata` must include:

| Field | Description |
| --- | --- |
| `raw_edit_payload` | Exact model output before parsing or linting. Preserve even when malformed. |
| `payload_parse_ok` / `payload_parse_error` | Flag + error string explaining whether the payload parsed. |
| `active_clause_id` | Clause string being targeted this round; never inferred downstream. |
| `contract_items` | Normalized list of clause dicts (id, label, description, tests, etc.). |
| `cgcs_state.row_quality` | Row-quality hints: `contract_quality`, `witness_count`, `payload_parse_ok`, `candidate_file_count`, `strategy_mode`, `used_fallback`, etc. |
| `cgcs_state.witnesses` | Structured witnesses with signatures, categories, expectations, linked clauses. |
| `regression_guard_ids` | Clauses that must not regress; emit `[]` if none. |
| `candidate_files` | Filtered list of files considered for editing. |
| `candidate_files_raw` / `candidate_files_filtered` | Full retrieval list vs. filtered edit targets. |

All fields must be emitted even when empty (use `[]` or `""`), so downstream audit tools never have to guess.

## Raw Payload vs. Parsed Edits

- `raw_edit_payload` is the literal response from the model (JSON string or prose). It must be stored before any parsing or linting.
- `payload_parse_ok` reflects whether the repo edit parser accepted the payload. If parsing fails, set `payload_parse_ok=false` and populate `payload_parse_error` with a descriptive string, but **do not** drop the raw payload.

## Candidate File Lists

- `candidate_files_raw`: the unfiltered retrieval output (Topcoder repo candidates, target files, expected files, etc.).
- `candidate_files_filtered`: the restricted list actually used for the current round (implementation targets, per-clause focus files, etc.).
- `candidate_files` mirrors `candidate_files_filtered` for backward compatibility.

These lists make trace backfills auditable and allow the strict builder to diagnose localization issues.

## Validating Instrumentation

Use the helper scripts before scaling to the full corpus:

1. Run a deterministic tiny subset to generate traces:
   ```bash
   python scripts/real_repo/run_tiny_cgcs_subset.py \
     --input data/topcoder/executable_subset.jsonl \
     --max-tasks 10 \
     --strategies cgcs \
     --output-dir reports/decomposition/real_world/real_repo_tiny \
     --seed 0
   ```

2. Audit the traces for strict-dataset readiness:
   ```bash
   python scripts/real_repo/audit_cgcs_trace_quality.py \
     --input-dir reports/decomposition/real_world/real_repo_tiny
   ```

The audit writes `trace_quality_summary.json` and `.md` summarizing the counts of rounds with contract items, active clause IDs, witnesses, raw payloads, candidate files, parse failures, and the number of rounds ready for the strict dataset. Iterate until `rounds_ready_for_strict_dataset > 0` and missing-field failure reasons drop.

By adhering to this contract, `scripts/build_cgcs_dataset.py --strict` can consistently produce `usable_rows > 0` with fewer missing-clause, empty-contract, or empty-payload errors.

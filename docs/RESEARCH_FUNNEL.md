# Research Funnel – Topcoder → CGCS → Batch

The Topcoder pipeline now exposes explicit stages so we can quantify progress from raw metadata to solved tasks. Each stage emits machine-readable counts (see `data/topcoder/funnel_report.json`) and should be cited whenever we describe coverage.

## Stage 1 – Indexed challenges

* Input: `data/raw/tasks.csv` + `challenge_data/challengeData_*/*.json`
* Output: `data/topcoder/corpus_index.jsonl` (`indexed_rows = 22,023`)
* Diagnostics: `data/topcoder/corpus_summary.json` (repo/test counts, duplicate clusters)

## Stage 2 – Likely executable

* Criteria: has repo signal (`repo_url`), mentions tests/tooling, ≥1 submission, Dev/QA track.
* Output: `data/topcoder/corpus_index.jsonl` rows with `likely_executable = true` (`16,562` challenges).

## Stage 3 – Usable CGCS rows

* Input: real-repo traces under `reports/decomposition/real_world/real_repo/runs`.
* Output: `data/cgcs/{train,dev,test}.jsonl`, plus `rejected.jsonl`.
* Current status: `60` total rows, `0` usable (all rejected due to missing clause IDs or weak contracts). See `data/cgcs/dataset_summary.json` for counts.

## Stage 4 – Batch-ready eval items

* Input: CGCS rows.
* Output: `openai_artifacts/eval_items_<split>.jsonl`, `openai_artifacts/batch_requests.jsonl`.
* Current status: `9` eval items in `openai_artifacts/eval_items_test.jsonl`, `0` batch requests generated (pending CGCS improvements).

## Stage 5 – Batch-run & solved tasks

* Input: Responses batch requests.
* Output: `openai_artifacts/batches/*.json`, `openai_artifacts/normalized/<batch_id>.jsonl`, grader summaries.
* Current status: No batches submitted; `batch_success_count = 0`, `solved_count = 0`.

---

Run `python scripts/topcoder/build_funnel_report.py` after every major update to refresh these counts. The resulting artifacts (`data/topcoder/funnel_report.json` and `reports/ase2026_aegis/funnel_snapshot.md`) should accompany benchmark claims so reviewers can trace where attrition occurs.

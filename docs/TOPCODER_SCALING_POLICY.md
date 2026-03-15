# Topcoder Scaling Policy

This repository supports end-to-end indexing of the full 22k Topcoder challenge archive, but only a subset is suitable for executable CGCS experiments. The policy below clarifies what is safe to do at 22k scale and what requires additional evidence.

## Allowed at 22k scale

* **Corpus indexing & metadata mining** – `scripts/topcoder/build_corpus_index.py` merges `data/raw/tasks.csv` with every `challenge_data/challengeData_*/*.json` window. The current summary (`data/topcoder/corpus_summary.json`) shows:
  * `indexed_rows = 22,023`
  * `repo_count = 16,568`
  * `test_count = 15,371`
  * `duplicate_group_count = 2,060`
* **Executable-subset selection** – `scripts/topcoder/select_executable_subset.py` filters by repo URL, test signal, submissions, and track, yielding `3,966` runnable challenges with rejection reasons in `data/topcoder/executable_subset_summary.json`.
* **Metadata-driven analytics** – Technologies, tags, prize pools, duplicate clusters, and heuristics (`heuristics_used`) can be analyzed across the entire corpus because the index is pure metadata.
* **Contract template mining & clustering** – Safe to operate over `data/topcoder/corpus_index.jsonl` or `executable_subset.jsonl` for retrieval, clustering, or prompt construction.
* **Offline prompt/eval generation** – Building CGCS eval items, batch requests, and funnel reports does not execute arbitrary code and is therefore safe to run at scale.

## Not assumed at 22k scale

* **Full repo checkout or repair** – Only the `3,966` high-confidence challenges in `data/topcoder/executable_subset.jsonl` should be considered for automated repairs. The rest of the corpus may lack repos, tests, or runnable assets.
* **Guaranteed CGCS usability** – The current CGCS build reports `60` rows (all rejected) because the latest real-repo traces still miss clause IDs or witnesses. Treat CGCS as instrumentation until future runs produce usable rows.
* **Batch success / solved tasks** – No Responses batches have been executed on the current dataset (`batch_request_count = 0`, `batch_success_count = 0` in `data/topcoder/funnel_report.json`). Do not claim solved tasks without normalized outputs and grader evidence.

## Funnel overview

| Stage | Count | Source |
| --- | ---: | --- |
| raw_corpus_count | 22,023 | `data/topcoder/funnel_report.json` |
| indexed_count | 22,023 | `data/topcoder/corpus_summary.json` |
| likely_executable_count | 16,562 | same |
| executable_subset_count | 3,966 | `data/topcoder/executable_subset_summary.json` |
| usable_cgcs_row_count | 60 (0 usable) | `data/cgcs/dataset_summary.json` |
| eval_item_count | 9 | `openai_artifacts/eval_items_test.jsonl` |
| batch_request_count | 0 | `openai_artifacts/batch_request_summary.json` |
| batch_success_count | 0 | `openai_artifacts/normalized/latest_summary.csv` |
| solved_count | 0 | `data/topcoder/funnel_report.json` |

Use `python scripts/topcoder/build_funnel_report.py` to refresh the counts whenever new data is ingested. These numbers must be cited in paper drafts and reports so reviewers can see the exact attrition at each stage.

## Summary

Operate freely on metadata-level tasks (indexing, clustering, contract mining) for all 22k challenges. Restrict runnable experiments to the executable subset, verify CGCS usability via `data/cgcs/dataset_summary.json`, and only claim solved tasks once the Responses batch pipeline produces normalized outputs and graders confirm success.

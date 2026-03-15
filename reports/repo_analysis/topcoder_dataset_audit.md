# Topcoder Dataset Audit

## 1. Where the challenge records originate
- **Official API** – `init.py` / `setUp.py` call `fetch_functions.get_data`, which paginates `/v5/challenges` using the retry helper in `http_utils.py`. Each payload is normalized through `process.format_challenge` before being written to `challenge_data/challengeData_<window>/pageN.json`.  
- **Enrichment endpoints** – Registrants, submissions, and member profiles/skills are fetched via the helpers in `fetch_functions.py` (`fetch_challenge_registrants`, `fetch_challenge_submissions`, `fetch_member_data`, `fetch_member_skills`). These calls run inside `uploader.Uploader.load_challenge_members` and `upload_members` so the MySQL tables track registrant activity per challenge.  
- **Legacy Excel backfill** – `legacy_excel_loader.py` ingests `old_Challenges.xlsx`, routes each row through `process.format_legacy_excel_row`, and produces a `challengeData_legacy_excel` window that can be uploaded the same way as API downloads.  
- **Corpus index** – `scripts/topcoder/build_corpus_index.py` merges every JSON window with `data/raw/tasks.csv`, attaches repo/test heuristics, records duplicate keys, and emits the authoritative manifest under `data/topcoder/corpus_index.jsonl` + `corpus_summary.json`.

## 2. Can we reproduce the 22 023-challenge claim?
- Yes. Running `python scripts/export_real_tasks.py --challenge-dir challenge_data --output-dir data/raw` regenerates `data/raw/tasks.csv`. Loading the file with pandas (`len(pd.read_csv("data/raw/tasks.csv"))`) yields **22 023 rows with 22 023 unique `task_id`s** (verified in this session).  
- `data/topcoder/corpus_summary.json`—written by `scripts/topcoder/build_corpus_index.py`—reports `indexed_rows=22,023`, cross-checking the same count after merging all API + Excel windows.  
- `data/topcoder/funnel_report.json` (built by `scripts/topcoder/build_funnel_report.py`) repeats these counts under `raw_corpus_count` and `indexed_count`, proving the number is reproducible from committed assets plus one script invocation.

## 3. Authoritative files, tables, and manifests
- **Raw evidence** – `challenge_data/challengeData_*/*.json` (API windows), `challenge_data/challengeData_legacy_excel/*.json`, and the curated CSV trio in `data/raw/{tasks,workers,interactions}.csv`.  
- **Warehouse mirror** – MySQL tables defined in `schema_registry.py` and populated by `uploader.Uploader` + `dbConnect.dbConnect`. These tables remain the source of truth for registrants/submissions/members and can be re-exported via `dbConnect.excel_uploader`.  
- **Corpus artifacts** – `data/topcoder/corpus_index.jsonl`, `corpus_summary.json`, `executable_subset.jsonl`, and `executable_subset_summary.json` (plus `executable_subset_rejections.jsonl`). These capture every challenge, runnable subset decisions, and rejection reasons.  
- **Processed bundle** – `data/processed/{tasks,workers,interactions,market}.{parquet,csv}` + `metadata.json` produced by `src/data/preprocess`. RL, decomposition, and regression pipelines depend on these tables.  
- **Funnel + source acquisition** – `data/topcoder/funnel_report.json`, `reports/ase2026_aegis/funnel_snapshot.md`, `data/topcoder/{artifact_candidates,repo_candidates,repo_fetch_manifest,repo_snapshots,workspace_manifest,source_acquisition_report}.json[l]`. These track downstream filtering, repo discovery, and workspace prep.

## 4. Deduplication logic
- `scripts/export_real_tasks._iter_challenge_payloads` keeps a `seen_ids` dict so later JSON windows overwrite older copies before writing `data/raw/tasks.csv`. Legacy Excel rows lacking `challengeId` raise `ValueError` and are skipped.  
- `scripts/topcoder/build_corpus_index.py` adds `duplicate_group_key` (normalized repo URL or title+track) and stores duplicate clusters inside `corpus_summary.json`.  
- `scripts/topcoder/select_executable_subset.py` maintains `seen_ids` and `seen_groups` to avoid duplicates when constructing `executable_subset.jsonl`; rejection reasons (`duplicate`, `missing_repo`, `missing_test_signal`, `weak_executable_signal`, etc.) are logged to `executable_subset_rejections.jsonl`.  
- MySQL inserts always use `ON DUPLICATE KEY UPDATE` (see `dbConnect.upload_data`), so repeated ETL passes update rows in place keyed by `challengeId`/`legacyId`/`memberHandle`.  
- Repo candidates are deduplicated by `normalized_repo_key` inside `src/decomposition/topcoder/discovery`, ensuring clone/download runs revisit each repo at most once.

## 5. Gaps, uncertainties, and credential requirements
- **Bearer token needed for submissions** – `fetch_challenge_submissions` only hits `/v5/submissions` when `TOPCODER_BEARER_TOKEN` is set; otherwise it logs a warning and returns an empty set, forcing `scripts/export_real_tasks.py` to synthesize submission order.  
- **Database credentials** – MySQL ingest requires the `TOPCODER_DB_*` environment variables (or `.env`). Without them the ETL cannot refresh the warehouse, although the committed CSV bundle keeps the dataset usable.  
- **Legacy Excel coverage** – The manual XML reader only supports `.xlsx`, not `.xls`, and still depends on well-formed column headers; malformed legacy rows are skipped.  
- **Timestamps** – `process.format_challenge` swallows unparsable datetime strings (returns `None`), so a minority of legacy rows may lack registration/submission timestamps.  
- **Repo heuristics** – URLs embedded in challenge descriptions are heuristic; some duplicates point to docs/figma links rather than real source repos, which is why the executable subset applies conservative filters (`require_tests`, `min_submissions=1`).  
- **Networked stages** – Repo fetching (`scripts/topcoder/fetch_topcoder_repos.py`) requires outbound network access and `git` tooling. All other analysis scripts (corpus index, funnel, preprocessing, RL) run entirely on committed data.

In short, every Topcoder record in this repo can be traced from `challenge_data/**` → `data/raw/*.csv` → MySQL tables → `data/topcoder/*.jsonl` → `data/processed/*.parquet`, and the 22 023‑challenge figure is verifiable via both the exported CSV and the corpus summary.

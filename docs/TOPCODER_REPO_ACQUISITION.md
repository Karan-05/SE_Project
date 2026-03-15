# Topcoder Repository Acquisition Pipeline

This repo now exposes a four-stage acquisition pipeline that separates “repo discovery” from actual cloning and workspace preparation. A challenge can be *likely executable* in the funnel yet never yield a runnable workspace if no public repo exists. The stages below keep that distinction explicit and machine-auditable.

## 1. Discovery

`scripts/topcoder/discover_repo_candidates.py` inspects:

- `data/raw/tasks.csv`
- archived API windows (`data/raw/page*.json.gz`)
- any `challenge_data/challengeData_*` exports
- the existing `data/topcoder/corpus_index.jsonl`

It extracts GitHub/GitLab/Bitbucket URLs from explicit repo fields, attachments, and free text, normalizes them (ssh/https), scores confidence, and emits:

- `data/topcoder/repo_candidates.jsonl`
- `data/topcoder/repo_candidates_summary.json`

Use `--max-records`, `--challenge-id`, and `--min-confidence` for small slices. Example dry-run on two IDs:

```bash
python scripts/topcoder/discover_repo_candidates.py \
  --tasks data/raw/tasks.csv \
  --pages-glob "data/raw/page*.json.gz" \
  --challenge-id 123 --challenge-id 456 \
  --min-confidence medium --max-records 500
```

At this stage we only know “discovered_repo_candidate = true/false” per challenge; nothing has been cloned.

## 2. Fetch / Snapshotting

`scripts/topcoder/fetch_topcoder_repos.py` deduplicates candidates by normalized repo key, optionally filters by challenge IDs, and either dry-runs (`--dry-run`) or clones/fetches high-confidence repos into `data/topcoder/repos/…`. It records success/failure counts plus error metadata in:

- `data/topcoder/repo_fetch_manifest.jsonl`
- `data/topcoder/repo_fetch_summary.json`

Use `--max-repos`, `--min-confidence`, `--dry-run`, and `--max-workers` to scale gradually. A dry-run that only builds the manifest:

```bash
python scripts/topcoder/fetch_topcoder_repos.py \
  --input data/topcoder/repo_candidates.jsonl \
  --repo-root data/topcoder/repos \
  --dry-run \
  --max-repos 50
```

After cloning, `scripts/topcoder/build_repo_snapshots.py` inspects each repo, captures commit/branch, lists top-level files, detects languages/build systems/test hints, and writes:

- `data/topcoder/repo_snapshots.jsonl`
- `data/topcoder/repo_snapshots_summary.json`

If a repo is already present locally the script just refreshes metadata; missing repos are skipped.

## 3. Workspace Preparation

`scripts/topcoder/prepare_workspaces.py` builds per-repo workspace manifests (install/build/test commands, env hints, prep statuses) from the snapshot file:

- `data/topcoder/workspace_manifest.jsonl`
- `data/topcoder/workspace_summary.json`

Install commands are *not* executed unless `--run-install` is passed; even then the script uses bounded timeouts and reports failures rather than hiding them. Most users should keep the default manifest-only mode.

## 4. Acquisition Reporting

`scripts/topcoder/build_repo_acquisition_report.py` aggregates the pipeline into machine- and human-readable summaries:

- `data/topcoder/repo_acquisition_report.json`
- `reports/ase2026_aegis/repo_acquisition_snapshot.md`

Counts include “candidate_count”, “fetched_repo_count”, “snapshot_count”, “workspace_manifest_count”, and “likely_runnable_workspace_count” to make gaps obvious. If a claim such as “22,023 challenges are runnable” were ever made, it would now need to be backed by these manifests.

## Interpreting Failures

- Discovery failures mean “no repo URL in available metadata” – credentials or attachments may still be missing.
- Fetch failures surface git errors (`clone_status = failed` with error_type/message) so one broken repo doesn’t halt the batch.
- Snapshot gaps typically mean the filesystem path vanished.
- Workspace gaps mark challenges without reliable install/build/test heuristics; these remain “likely executable” only after manual inspection.

Because many past Topcoder tasks point to proprietary systems, expect the majority of the 22k challenges to stop at discovery or fetch. The manifests and summaries make that fact explicit so later stages and reviewers can tell how many repos were actually cloned versus merely referenced.

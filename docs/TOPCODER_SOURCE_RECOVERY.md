# Topcoder Source Recovery Guide

This document captures the guardrails and entrypoints for recovering source trees from the Topcoder corpus. The acquisition funnel is intentionally multi-stage so that we can record every artifact, classify it, and only expend network effort on legitimate source repositories.

## Artifact vs. Repo Candidates

1. **Artifact discovery** scans structured fields, attachments, and free-form descriptions. Every URL is emitted as an `artifact_candidate` with its normalized host, path, artifact type, classification reason, and suggested acquisition strategy.
2. **Repo candidate filtering** selects only artifacts with source-bearing strategies (`clone`, `clone_or_source_download`, or `download_archive`). API endpoints, documentation pages, direct IP app URLs, and other non-source artifacts are retained for auditability but are explicitly marked for rejection.
3. **Repo fetching** respects the acquisition strategy:
   - `clone`: validate the remote with `git ls-remote`, perform shallow clone, and record the resolved commit.
   - `clone_or_source_download`: attempt a clone first, and optionally derive GitHub/GitLab/Bitbucket archive URLs if `--prefer-archive-fallback` is set.
   - `download_archive`: download and unpack the provided archive, recording the hash and origin.

## Why Many URLs Are Rejected

- API endpoints (e.g., `*.execute-api.*`, `api.*`, `*amazonaws.com`) cannot be cloned; they expose services, not repositories.
- App/demo URLs and bare IP addresses typically serve deployed frontends or staging instances rather than code.
- Documentation and help portals are valuable references but not source trees.
- Raw code file links (single `*.py`, `*.js` blobs) are catalogued for forensic use, yet they are not treated as recoverable repos unless enough files can be bundled into a pseudo-workspace.

Every rejection is written to `data/topcoder/repo_fetch_manifest.jsonl` with a `clone_status` of `rejected` and a clear `rejection_reason`. This keeps the pipeline auditable and prevents silent failures.

## Source Archives and Synthetic Workspaces

- Source archives (`*.zip`, `*.tar.gz`, host `/archive/` links) are accepted when they appear to contain complete source bundles. The fetcher unpacks them into deterministic directories, marks `source_origin="archive"`, and records `archive_hash` for provenance.
- When no original repo can be recovered for a challenge, downstream tooling may emit **synthetic workspaces**. These are metadata-only entries that capture challenge context but set `synthetic_workspace=true` and `original_repo_recovered=false`. They **must not** be mistaken for the original repository and should be excluded from runnable evaluations.

## Running the Pipeline

### 1. Discover artifacts and repo candidates

```bash
python scripts/topcoder/discover_repo_candidates.py \
  --tasks data/raw/tasks.csv \
  --pages-glob "data/raw/page*.json.gz" \
  --challenge-data-glob "challenge_data/challengeData_*/*.json" \
  --corpus-index data/topcoder/corpus_index.jsonl
```

Outputs:
- `data/topcoder/artifact_candidates.jsonl`
- `data/topcoder/artifact_candidates_summary.json`
- `data/topcoder/repo_candidates.jsonl`
- `data/topcoder/repo_candidates_summary.json`

### 2. Inspect recovery posture before fetching

```bash
python scripts/topcoder/debug_repo_recovery.py
```

This produces `data/topcoder/repo_recovery_debug.json` and `reports/ase2026_aegis/repo_recovery_debug.md` with host distributions, rejection reasons, and sample recoveries.

### 3. High-recall dry run

```bash
python scripts/topcoder/fetch_topcoder_repos.py \
  --input data/topcoder/repo_candidates.jsonl \
  --repo-root data/topcoder/repos \
  --dry-run \
  --recovery-mode high-recall \
  --allowed-hosts github.com,gitlab.com,bitbucket.org \
  --reject-host-patterns execute-api,amazonaws.com,cloudfront.net \
  --prefer-archive-fallback \
  --skip-non-source \
  --emit-rejections
```

Records every planned action and rejection without touching the network.

### 4. Real fetch (first 100 repos)

```bash
python scripts/topcoder/fetch_topcoder_repos.py \
  --input data/topcoder/repo_candidates.jsonl \
  --repo-root data/topcoder/repos \
  --max-repos 100 \
  --recovery-mode high-recall \
  --allowed-hosts github.com,gitlab.com,bitbucket.org \
  --reject-host-patterns execute-api,amazonaws.com,cloudfront.net \
  --prefer-archive-fallback \
  --skip-non-source \
  --emit-rejections
```

### 5. Build snapshots and workspaces

```bash
python scripts/topcoder/build_repo_snapshots.py --repo-root data/topcoder/repos
python scripts/topcoder/prepare_workspaces.py --snapshots data/topcoder/repo_snapshots.jsonl
```

Each snapshot and workspace entry records `source_origin`, `source_url`, and whether the original repo was recovered vs. synthesized.

### 6. Source acquisition report

```bash
python scripts/topcoder/build_repo_acquisition_report.py
```

Outputs:
- `data/topcoder/source_acquisition_report.json`
- `reports/ase2026_aegis/source_acquisition_snapshot.md`

These files highlight artifact counts, repo candidate coverage, fetch successes/failures, and downstream workspace readiness.

## High-Recall Mode Safety

`--recovery-mode high-recall` turns on archive fallbacks and keeps raw code artifacts in the audit trail, but it still honors `--allowed-hosts`, `--reject-host-patterns`, and `--skip-non-source`. This ensures the pipeline is aggressive about recovering *available* code while never fabricating repositories that do not exist.

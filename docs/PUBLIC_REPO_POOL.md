# Public Repo Pool for CGCS Harness Testing

The Topcoder recovery funnel still drives the long–term data mission, but the teams
need a clean set of real repositories **right now** to test the CGCS harness,
runtime instrumentation, and workspace preparation logic. The public repo pool
is that bootstrap resource: it gathers ≥100 active GitHub repositories with
tests, build files, and auditable metadata so we can validate the harness without
waiting for the entire Topcoder archive to be runnable.

The track reuses none of the noisy Topcoder URLs and keeps its artifacts in
`data/public_repos/`. It does **not** imply that the Topcoder corpus is solved.

## Pipeline Overview

| Stage | Command | Outputs |
| --- | --- | --- |
| Discover candidates | `make public_repo_discover` | `data/public_repos/repo_candidates.jsonl`, `repo_candidates_summary.json` |
| Score + Select 100 | `make public_repo_select` | `data/public_repos/repo_pool_100.jsonl`, `repo_selection_summary.json`, `repo_pool_100_summary.json` |
| Clone/fetch | `make public_repo_fetch` | `data/public_repos/repo_fetch_manifest.jsonl`, `repo_fetch_summary.json`, repos under `data/public_repos/repos/` |
| Snapshot build/test signals | `make public_repo_snapshots` | `data/public_repos/repo_snapshots.jsonl`, `repo_snapshots_summary.json` |
| Prepare workspaces + CGCS subset | `make public_repo_workspaces` | `workspace_manifest.jsonl`, `cgcs_seed_pool.jsonl` |
| Build JSON+Markdown report | `make public_repo_report` | `data/public_repos/public_repo_report.json`, `reports/ase2026_aegis/public_repo_snapshot.md` |

Each script accepts CLI options (language filters, per-language targets,
max-per-owner caps, min stars, dry-run fetches, etc.). See the `--help` flag on
each script for details.

## Discovery & Selection

`scripts/public_repos/discover_public_repos.py` pulls two sources:

1. benchmark seeds (SWE-bench/Cgcs manifests when present)
2. GitHub search queries (authenticated via `GITHUB_TOKEN`)

Candidates are deduplicated by repo key, annotated with build/test/CI signals
via the GitHub contents API, and scored by suitability (active maintenance,
license, build/test files, size, recency).

`scripts/public_repos/select_repo_pool.py` enforces language targets
(default 40 Python, 40 JS/TS, 20 Java/other), caps per-owner representation,
and emits a deterministic `repo_pool_100.jsonl` plus summaries.

## Fetch, Snapshot, Workspaces

* `scripts/public_repos/fetch_repo_pool.py` shallow-clones each repo (with
  optional dry-run validation) and records status, branch, commit, errors, etc.
* `scripts/public_repos/build_repo_snapshots.py` inspects the clones to
  enumerate languages, build systems, CI/test signals, and top-level files.
* `scripts/public_repos/prepare_workspaces.py` uses the snapshot metadata to
  propose install/build/test commands, compute runnable-confidence scores, and
  carve out `cgcs_seed_pool.jsonl` (repos with build + test files and sufficient
  confidence).

None of these steps run the commands automatically—they only propose safe,
auditable defaults for harness operators.

## Reporting & Usage

`scripts/public_repos/build_public_repo_report.py` aggregates the stage
summaries into machine-readable JSON (`data/public_repos/public_repo_report.json`)
and a Markdown snapshot (`reports/ase2026_aegis/public_repo_snapshot.md`). The
Markdown explicitly calls out that this is an engineering bootstrap pool, not a
replacement for the Topcoder recovery funnel.

Use the workspace manifest when testing CGCS/runtime instrumentation, but keep
the following limitations in mind:

* GitHub search still requires a valid token and can exhaust rate limits.
* Build/test detection is heuristic; verify commands before running code in
  automation.
* The pool focuses on Python/JS/TS/Java repos; other ecosystems are possible
  but not guaranteed.
* This track does **not** map back to individual Topcoder challenges.

When the Topcoder recovery pipeline is ready, its outputs remain authoritative
for the 22,023-challenge audit. Until then, this public repo pool provides the
100+ real repositories needed to exercise CGCS instrumentation honestly.

# Topcoder Repo Task Snapshots

This directory hosts per-task manifests plus their `ground_truth.patch` files.
Use `scripts/regenerate_ground_truth_patches.py` to rebuild the patches from the
clean snapshot in `experiments/real_repos_snapshots/tc-template-node-postgres.base`
and the solved snapshot `experiments/real_repos_snapshots/tc-template-node-postgres.solved`.
Each challenge directory should follow:

```
experiments/real_repo_tasks/topcoder/<challenge_id>/
    task.json
    repo/  # git-free snapshot with build + test scripts
```

`task.json` must include `repo_dir` (e.g., "repo") or an absolute `repo_path`, plus metadata such as `target_files`, `test_commands`, `dataset_source`, and `reportable` flags. If a `ground_truth.patch` file lives next to `task.json`, `scripts/ingest_repo_tasks.py` will automatically point the manifest metadata at that patch to aid localization evaluation.

Available tasks:

- `a160ded4_problem_listing` — SRM list endpoint (difficulty filtering, metadata summary, sorted component hints). Runs `npm test -- --reporter dot test/problems.list.spec.js`.
- `a160ded4_problem_detail` — SRM detail endpoint (component stats aggregation + 404 JSON error). Runs `npm test -- --reporter dot test/problems.detail.spec.js`.
- `a160ded4_problem_tags_filter` — SRM list endpoint tag filters (comma-separated or array, metadata exposes normalized tags). Runs `npm test -- --reporter dot test/problems.tags.spec.js`.
- `a160ded4_component_metadata_summary` — SRM list endpoint component metadata totals (language + status aggregates respecting filters/limits). Runs `npm test -- --reporter dot test/problems.components.meta.spec.js`.

All tasks target `experiments/real_repos/tc-template-node-postgres`, require multi-file controller/service updates, and rely on `npm ci --no-audit --no-fund` before executing the tests.

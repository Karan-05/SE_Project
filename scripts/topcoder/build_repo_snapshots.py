#!/usr/bin/env python3
"""Build repo snapshot manifests for fetched Topcoder repositories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.decomposition.topcoder.repos import GitCommandError, repo_storage_path, run_git
from src.decomposition.topcoder.snapshot import RepoSnapshot, build_snapshot

SUCCESS_STATUSES = {"cloned", "updated", "archive_downloaded"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("data/topcoder/repos"))
    parser.add_argument("--fetch-manifest", type=Path, default=Path("data/topcoder/repo_fetch_manifest.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/topcoder/repo_snapshots.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/topcoder/repo_snapshots_summary.json"))
    return parser.parse_args()


def load_fetch_entries(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            entries.append(payload)
    return entries


def discover_local_repos(repo_root: Path) -> list[dict]:
    entries: list[dict] = []
    if not repo_root.exists():
        return entries
    for git_dir in repo_root.rglob(".git"):
        repo_path = git_dir.parent
        try:
            repo_key = str(repo_path.relative_to(repo_root))
        except ValueError:
            repo_key = repo_path.name
        entries.append(
            {
                "normalized_repo_key": repo_key,
                "repo_url": "",
                "challenge_ids": [],
                "local_path": str(repo_path),
                "clone_status": "unknown",
            }
        )
    return entries


def resolve_git_metadata(local_path: Path, entry: dict) -> tuple[str | None, str | None]:
    commit = entry.get("resolved_commit")
    branch = entry.get("default_branch") or entry.get("branch")
    if local_path.exists() and (local_path / ".git").exists():
        if not commit:
            try:
                commit = run_git(["rev-parse", "HEAD"], cwd=local_path).stdout.strip()
            except GitCommandError:
                commit = None
        if not branch:
            try:
                branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=local_path).stdout.strip()
            except GitCommandError:
                branch = None
    return commit, branch


def main() -> None:
    args = parse_args()
    entries = load_fetch_entries(args.fetch_manifest)
    if not entries:
        entries = discover_local_repos(args.repo_root)
    snapshots: list[RepoSnapshot] = []
    languages_count: dict[str, int] = {}
    build_count: dict[str, int] = {}
    runnable = 0
    origin_counts: dict[str, int] = {}
    for entry in entries:
        status = entry.get("clone_status")
        if status not in SUCCESS_STATUSES:
            continue
        normalized_repo_key = entry.get("normalized_repo_key")
        repo_url = entry.get("repo_url")
        challenge_ids = entry.get("challenge_ids") or []
        local_path = entry.get("local_path")
        path = Path(local_path) if local_path else repo_storage_path(args.repo_root, normalized_repo_key)
        if not path or not path.exists():
            continue
        commit, branch = resolve_git_metadata(path, entry)
        source_origin = entry.get("source_origin") or ("clone" if status in {"cloned", "updated"} else "archive")
        source_url = entry.get("source_url") or repo_url
        archive_hash = entry.get("archive_hash")
        snapshot = build_snapshot(
            repo_url=repo_url,
            local_path=path,
            normalized_repo_key=normalized_repo_key,
            challenge_ids=challenge_ids,
            resolved_commit=commit,
            branch=branch,
            source_origin=source_origin,
            source_url=source_url,
            archive_hash=archive_hash,
        )
        snapshots.append(snapshot)
        for lang in snapshot.detected_languages:
            languages_count[lang] = languages_count.get(lang, 0) + 1
        for build in snapshot.detected_build_systems:
            build_count[build] = build_count.get(build, 0) + 1
        if snapshot.likely_runnable:
            runnable += 1
        origin_counts[source_origin] = origin_counts.get(source_origin, 0) + 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for snapshot in snapshots:
            handle.write(json.dumps(snapshot.to_dict()) + "\n")
    summary = {
        "snapshot_count": len(snapshots),
        "detected_languages": languages_count,
        "detected_build_systems": build_count,
        "likely_runnable": runnable,
        "source_origin_counts": origin_counts,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with args.summary.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"Repo snapshot manifest -> {args.output}")
    print(f"Repo snapshot summary -> {args.summary}")


if __name__ == "__main__":
    main()

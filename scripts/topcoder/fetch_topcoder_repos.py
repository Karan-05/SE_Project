#!/usr/bin/env python3
"""Clone Topcoder repository candidates into a local workspace."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


from src.decomposition.topcoder.repos import (
    RepoCandidateRecord,
    RepoFetchResult,
    build_fetch_result,
    group_repo_candidates,
    parse_candidate,
    repo_storage_path,
)

SOURCELIKE_ARTIFACT_TYPES = {"git_repo", "git_host_repo_page", "source_archive"}


def _parse_csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/topcoder/repo_candidates.jsonl"))
    parser.add_argument("--repo-root", type=Path, default=Path("data/topcoder/repos"))
    parser.add_argument("--manifest", type=Path, default=Path("data/topcoder/repo_fetch_manifest.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/topcoder/repo_fetch_summary.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--max-repos", type=int, default=None)
    parser.add_argument("--min-confidence", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--retry-count", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--challenge-id", action="append", default=None, help="Limit fetches to specific challenge IDs.")
    parser.add_argument("--recovery-mode", choices=("standard", "high-recall"), default="standard")
    parser.add_argument("--allowed-hosts", type=str, default=None)
    parser.add_argument("--reject-host-patterns", type=str, default=None)
    parser.add_argument("--prefer-archive-fallback", action="store_true")
    parser.add_argument("--skip-non-source", action="store_true")
    parser.add_argument("--emit-rejections", action="store_true", help="Print rejected groups to stdout.")
    return parser.parse_args()


def load_candidates(path: Path) -> list[RepoCandidateRecord]:
    records: list[RepoCandidateRecord] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            record = parse_candidate(payload)
            if record:
                records.append(record)
    return records


def make_rejection_result(
    group,
    repo_root: Path,
    reason: str,
    details: str | None = None,
) -> RepoFetchResult:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    dest = repo_storage_path(repo_root, group.normalized_repo_key)
    candidate_urls = sorted(group.candidate_urls) if group.candidate_urls else [group.repo_url]
    return RepoFetchResult(
        repo_url=group.repo_url,
        normalized_repo_key=group.normalized_repo_key,
        repo_host=group.repo_host,
        challenge_ids=sorted(group.challenge_ids),
        acquisition_strategy=group.acquisition_strategy,
        artifact_type=group.artifact_type,
        clone_status="rejected",
        local_path=str(dest),
        source_origin=None,
        source_url=None,
        candidate_urls=candidate_urls,
        rejection_reason=reason,
        rejection_details=details,
        fetch_timestamp=timestamp,
    )


def as_dict(result: RepoFetchResult) -> dict:
    return {
        "repo_url": result.repo_url,
        "normalized_repo_key": result.normalized_repo_key,
        "repo_host": result.repo_host,
        "challenge_ids": result.challenge_ids,
        "acquisition_strategy": result.acquisition_strategy,
        "artifact_type": result.artifact_type,
        "clone_status": result.clone_status,
        "local_path": result.local_path,
        "source_origin": result.source_origin,
        "source_url": result.source_url,
        "candidate_urls": result.candidate_urls,
        "rejection_reason": result.rejection_reason,
        "rejection_details": result.rejection_details,
        "error_type": result.error_type,
        "error_message": result.error_message,
        "default_branch": result.default_branch,
        "resolved_commit": result.resolved_commit,
        "fetch_timestamp": result.fetch_timestamp,
        "license_info": result.license_info,
        "archive_hash": result.archive_hash,
    }


def main() -> None:
    args = parse_args()
    candidates = load_candidates(args.input)
    allowed_ids = {value.strip() for value in (args.challenge_id or []) if value and value.strip()}
    if allowed_ids:
        candidates = [record for record in candidates if record.challenge_id in allowed_ids]
    groups = group_repo_candidates(
        records=candidates,
        min_confidence=args.min_confidence,
        max_repos=None,
    )
    allowed_hosts = {host.lower() for host in _parse_csv_list(args.allowed_hosts)}
    reject_patterns = [pattern.lower() for pattern in _parse_csv_list(args.reject_host_patterns)]
    prefer_archive_fallback = args.prefer_archive_fallback or args.recovery_mode == "high-recall"
    args.repo_root.mkdir(parents=True, exist_ok=True)
    rejection_results: list[RepoFetchResult] = []
    rejection_reason_counts: dict[str, int] = {}
    eligible_groups: list = []

    git_hosts = {"github.com", "gitlab.com", "bitbucket.org"}
    for group in groups:
        host = (group.repo_host or "").lower()
        reason = None
        details = None
        if allowed_hosts and host not in allowed_hosts:
            reason = "host_not_allowed"
            details = host
        elif reject_patterns and any(pattern in host for pattern in reject_patterns):
            reason = "host_reject_pattern"
            details = host
        elif (
            host in git_hosts
            and group.normalized_url
            and "/" not in group.normalized_url.replace(f"https://{host}/", "", 1)
        ):
            reason = "invalid_repo_slug"
            details = group.normalized_url
        elif args.skip_non_source and group.artifact_type not in SOURCELIKE_ARTIFACT_TYPES:
            reason = "artifact_type_filtered"
            details = group.artifact_type
        elif args.recovery_mode == "standard" and group.acquisition_strategy == "download_archive" and not prefer_archive_fallback:
            reason = "archive_strategy_requires_high_recall"
            details = group.acquisition_strategy
        if reason:
            rejection_results.append(make_rejection_result(group, args.repo_root, reason, details))
            rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1
            if args.emit_rejections:
                note = f" ({details})" if details else ""
                print(f"[reject] {group.normalized_repo_key}: {reason}{note}")
            continue
        eligible_groups.append(group)

    if args.max_repos is not None:
        eligible_groups = eligible_groups[: args.max_repos]

    fetch_results: list[RepoFetchResult] = []
    if eligible_groups:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_map = {
                executor.submit(
                    build_fetch_result,
                    group,
                    args.repo_root,
                    args.dry_run,
                    args.timeout_seconds,
                    args.retry_count,
                    prefer_archive_fallback,
                ): group
                for group in eligible_groups
            }
            for future in as_completed(future_map):
                fetch_results.append(future.result())
    results: list[RepoFetchResult] = fetch_results + rejection_results
    results.sort(key=lambda r: r.normalized_repo_key)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(as_dict(result)) + "\n")

    error_types: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    source_origin_counts: dict[str, int] = {}
    clone_attempted = 0
    clone_success = 0
    clone_failed = 0
    archive_attempted = 0
    archive_success = 0
    archive_failed = 0
    rejected_count = 0
    for result in results:
        status_counts[result.clone_status] = status_counts.get(result.clone_status, 0) + 1
        if result.source_origin:
            source_origin_counts[result.source_origin] = source_origin_counts.get(result.source_origin, 0) + 1
        if result.error_type:
            error_types[result.error_type] = error_types.get(result.error_type, 0) + 1
        if result.clone_status == "rejected":
            rejected_count += 1
            continue
        if result.clone_status == "dry_run":
            continue
        if result.source_origin == "clone":
            clone_attempted += 1
            if result.clone_status in {"cloned", "updated"}:
                clone_success += 1
            elif result.clone_status == "failed":
                clone_failed += 1
        if result.source_origin == "archive":
            archive_attempted += 1
            if result.clone_status == "archive_downloaded":
                archive_success += 1
            elif result.clone_status == "failed":
                archive_failed += 1

    summary = {
        "input_candidates": len(candidates),
        "deduped_repo_count": len(groups),
        "eligible_group_count": len(eligible_groups),
        "rejected_group_count": rejected_count,
        "clone_attempted_count": clone_attempted,
        "clone_success_count": clone_success,
        "clone_failed_count": clone_failed,
        "archive_download_attempted_count": archive_attempted,
        "archive_download_success_count": archive_success,
        "archive_download_failed_count": archive_failed,
        "rejected_non_repo_count": rejected_count,
        "dry_run": args.dry_run,
        "min_confidence": args.min_confidence,
        "recovery_mode": args.recovery_mode,
        "prefer_archive_fallback": prefer_archive_fallback,
        "allowed_hosts": sorted(allowed_hosts),
        "reject_host_patterns": reject_patterns,
        "error_types": error_types,
        "status_counts": status_counts,
        "source_origin_counts": source_origin_counts,
        "rejection_reasons": rejection_reason_counts,
        "challenge_filter_count": len(allowed_ids),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with args.summary.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"Repo fetch manifest -> {args.manifest}")
    print(f"Repo fetch summary -> {args.summary}")


if __name__ == "__main__":
    main()

"""Clone and track the public repository pool."""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from src.decomposition.topcoder.repos import GitCommandError, ensure_repo

from .utils import now_utc_iso, write_json, write_jsonl


@dataclass(slots=True)
class RepoFetchRequest:
    repo_url: str
    repo_key: str
    local_path: Path
    metadata: dict[str, object]


@dataclass(slots=True)
class FetchOptions:
    dry_run: bool
    timeout: int
    retries: int
    validate_remote: bool


@dataclass(slots=True)
class FetchResult:
    repo_url: str
    repo_key: str
    status: str
    local_path: Path
    default_branch: str | None = None
    resolved_commit: str | None = None
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_utc_iso)

    def as_dict(self) -> dict[str, object]:
        payload = {
            "repo_url": self.repo_url,
            "repo_key": self.repo_key,
            "status": self.status,
            "local_path": str(self.local_path),
            "default_branch": self.default_branch,
            "resolved_commit": self.resolved_commit,
            "timestamp": self.timestamp,
            "error_message": self.error_message,
        }
        payload.update(self.metadata)
        return payload


def load_repo_pool(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def build_fetch_requests(records: Sequence[dict[str, object]], repo_root: Path) -> list[RepoFetchRequest]:
    # Resolve to absolute so ensure_repo's cwd=dest.parent works correctly.
    abs_root = repo_root.resolve()
    requests: list[RepoFetchRequest] = []
    for record in records:
        repo_key = record.get("repo_key")
        repo_url = record.get("repo_url")
        if not repo_key or not repo_url:
            continue
        local_path = abs_root / repo_key
        requests.append(
            RepoFetchRequest(
                repo_url=str(repo_url),
                repo_key=str(repo_key),
                local_path=local_path,
                metadata=record,
            )
        )
    return requests


def run_fetch(request: RepoFetchRequest, options: FetchOptions) -> FetchResult:
    if options.dry_run:
        return FetchResult(
            repo_url=request.repo_url,
            repo_key=request.repo_key,
            status="dry_run",
            local_path=request.local_path,
            metadata=request.metadata,
        )
    request.local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        status, branch, commit = ensure_repo(
            repo_url=request.repo_url,
            dest=request.local_path,
            timeout=options.timeout,
            retries=options.retries,
            validate_remote=options.validate_remote,
            shallow=True,
        )
        return FetchResult(
            repo_url=request.repo_url,
            repo_key=request.repo_key,
            status=status,
            local_path=request.local_path,
            default_branch=branch,
            resolved_commit=commit,
            metadata=request.metadata,
        )
    except GitCommandError as exc:
        return FetchResult(
            repo_url=request.repo_url,
            repo_key=request.repo_key,
            status="failed",
            local_path=request.local_path,
            error_message=str(exc),
            metadata=request.metadata,
        )


def fetch_repositories(
    requests: Sequence[RepoFetchRequest],
    options: FetchOptions,
    max_workers: int,
) -> list[FetchResult]:
    results: list[FetchResult] = []
    if not requests:
        return results
    with ThreadPoolExecutor(max_workers=max_workers or 4) as executor:
        future_map = {executor.submit(run_fetch, request, options): request for request in requests}
        for future in as_completed(future_map):
            results.append(future.result())
    results.sort(key=lambda item: item.repo_key)
    return results


def build_fetch_summary(results: Sequence[FetchResult]) -> dict[str, object]:
    status_counts = Counter(result.status for result in results)
    return {
        "generated_at": now_utc_iso(),
        "total": len(results),
        "status_counts": dict(status_counts),
        "successful": status_counts.get("cloned", 0) + status_counts.get("updated", 0),
        "failed": status_counts.get("failed", 0),
    }


def write_fetch_outputs(
    results: Sequence[FetchResult],
    manifest_path: Path,
    summary_path: Path,
) -> None:
    write_jsonl(manifest_path, (result.as_dict() for result in results))
    write_json(summary_path, build_fetch_summary(results))


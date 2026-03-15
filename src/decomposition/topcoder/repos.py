"""Helpers for working with Topcoder challenge repositories."""

from __future__ import annotations

import dataclasses
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, MutableMapping, Optional, Sequence, Set, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from . import CONFIDENCE_ORDER

KNOWN_HOST_ALIASES = {
    "github.com": "github.com",
    "www.github.com": "github.com",
    "gitlab.com": "gitlab.com",
    "www.gitlab.com": "gitlab.com",
    "bitbucket.org": "bitbucket.org",
    "www.bitbucket.org": "bitbucket.org",
}

LICENSE_FILENAMES = (
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
    "COPYING",
    "COPYRIGHT",
)

STRATEGY_PRIORITY = {
    "clone": 3,
    "clone_or_source_download": 2,
    "download_archive": 1,
}


@dataclass(slots=True)
class RepoURLInfo:
    """Normalized view of a repository URL."""

    original_url: str
    normalized_url: str
    repo_host: str
    repo_key: str
    repo_path: str


def _strip_git_suffix(value: str) -> str:
    return value[:-4] if value.endswith(".git") else value


def _normalize_path(path: str) -> str:
    cleaned = path.strip("/").split("/")
    if len(cleaned) >= 2:
        return "/".join(cleaned[:2])
    if cleaned:
        return cleaned[0]
    return ""


def normalize_repo_url(url: str) -> Optional[RepoURLInfo]:
    """Return normalized RepoURLInfo if the url looks like a git repo."""

    if not url:
        return None
    original = url.strip()
    if original.startswith("git@"):
        try:
            host_part, path_part = original.split(":", 1)
            host = host_part.replace("git@", "").strip().lower()
            path = _strip_git_suffix(path_part.strip("/"))
            norm_path = _normalize_path(path)
            if not norm_path:
                return None
            normalized_url = f"https://{host}/{norm_path}"
            repo_key = f"{host}/{norm_path}".lower()
            repo_host = KNOWN_HOST_ALIASES.get(host.lower(), host.lower())
            return RepoURLInfo(
                original_url=original,
                normalized_url=normalized_url,
                repo_host=repo_host,
                repo_key=repo_key,
                repo_path=norm_path.lower(),
            )
        except ValueError:
            return None
    try:
        parsed = urlparse(original)
        if not parsed.scheme:
            parsed = urlparse(f"https://{original.lstrip('/')}")
    except ValueError:
        return None
    host = (parsed.netloc or "").lower()
    repo_host = KNOWN_HOST_ALIASES.get(host, host)
    path = parsed.path or ""
    norm_path = _normalize_path(_strip_git_suffix(path))
    if not norm_path:
        return None
    if repo_host in {"github.com", "gitlab.com", "bitbucket.org"} and "/" not in norm_path:
        return None
    normalized_url = f"https://{repo_host}/{norm_path}"
    repo_key = f"{repo_host}/{norm_path}".lower()
    return RepoURLInfo(
        original_url=original,
        normalized_url=normalized_url,
        repo_host=repo_host,
        repo_key=repo_key,
        repo_path=norm_path.lower(),
    )


def repo_storage_path(repo_root: Path, repo_key: str) -> Path:
    return repo_root / repo_key


def confidence_allows(candidate_confidence: str, min_confidence: str) -> bool:
    return CONFIDENCE_ORDER.get(candidate_confidence, -1) >= CONFIDENCE_ORDER.get(min_confidence, 0)


@dataclass(slots=True)
class RepoCandidateRecord:
    challenge_id: str
    title: str
    candidate_url: str
    repo_url: str
    normalized_url: str
    repo_host: str
    normalized_repo_key: str
    source_field: str
    discovery_method: str
    confidence_score: str
    evidence_snippet: str = ""
    acquisition_strategy: str = "clone"
    artifact_type: str = "git_repo"
    classification_reason: str = ""
    notes: str = ""
    challenge_text_context: str = ""
    normalized_repo_url: Optional[str] = None


def parse_candidate(payload: MutableMapping[str, object]) -> Optional[RepoCandidateRecord]:
    repo_url = str(payload.get("repo_url") or payload.get("repoUrl") or "").strip()
    normalized_key = str(payload.get("normalized_repo_key") or "").strip()
    challenge_id = str(payload.get("challenge_id") or payload.get("task_id") or "").strip()
    if not (repo_url and normalized_key and challenge_id):
        return None
    title = str(payload.get("title") or payload.get("challenge_title") or "").strip()
    record = RepoCandidateRecord(
        challenge_id=challenge_id,
        title=title,
        candidate_url=str(payload.get("candidate_url") or repo_url).strip() or repo_url,
        repo_url=repo_url,
        normalized_url=str(payload.get("normalized_url") or repo_url).strip() or repo_url,
        repo_host=str(payload.get("repo_host") or ""),
        normalized_repo_key=normalized_key,
        source_field=str(payload.get("source_field") or ""),
        discovery_method=str(payload.get("discovery_method") or ""),
        confidence_score=str(payload.get("confidence_score") or "low"),
        evidence_snippet=str(payload.get("evidence_snippet") or ""),
        acquisition_strategy=str(payload.get("acquisition_strategy") or payload.get("repo_strategy") or "clone").strip()
        or "clone",
        artifact_type=str(payload.get("artifact_type") or payload.get("repo_artifact_type") or "git_repo").strip()
        or "git_repo",
        classification_reason=str(payload.get("classification_reason") or ""),
        notes=str(payload.get("notes") or ""),
        challenge_text_context=str(payload.get("challenge_text_context") or ""),
        normalized_repo_url=(str(payload.get("normalized_repo_url") or "").strip() or None),
    )
    return record


@dataclass(slots=True)
class RepoCandidateGroup:
    normalized_repo_key: str
    repo_host: str
    repo_url: str
    normalized_url: str
    best_confidence: str
    acquisition_strategy: str
    artifact_type: str
    classification_reason: str
    normalized_repo_url: Optional[str] = None
    challenge_ids: Set[str] = field(default_factory=set)
    titles: Set[str] = field(default_factory=set)
    records: List[RepoCandidateRecord] = field(default_factory=list)
    candidate_urls: Set[str] = field(default_factory=set)

    def to_manifest_stub(self) -> Dict[str, object]:
        return {
            "normalized_repo_key": self.normalized_repo_key,
            "repo_host": self.repo_host,
            "repo_url": self.repo_url,
            "best_confidence": self.best_confidence,
            "acquisition_strategy": self.acquisition_strategy,
            "artifact_type": self.artifact_type,
            "classification_reason": self.classification_reason,
            "challenge_ids": sorted(self.challenge_ids),
            "titles": sorted(self.titles),
        }


def group_repo_candidates(
    records: Iterable[RepoCandidateRecord],
    min_confidence: str = "low",
    max_repos: Optional[int] = None,
) -> List[RepoCandidateGroup]:
    by_key: Dict[str, RepoCandidateGroup] = {}
    for record in records:
        if not confidence_allows(record.confidence_score, min_confidence):
            continue
        group = by_key.get(record.normalized_repo_key)
        if group is None:
            group = RepoCandidateGroup(
                normalized_repo_key=record.normalized_repo_key,
                repo_host=record.repo_host,
                repo_url=record.repo_url,
                normalized_url=record.normalized_url,
                best_confidence=record.confidence_score,
                acquisition_strategy=record.acquisition_strategy,
                artifact_type=record.artifact_type,
                classification_reason=record.classification_reason,
                normalized_repo_url=record.normalized_repo_url,
            )
            by_key[record.normalized_repo_key] = group
        current_priority = STRATEGY_PRIORITY.get(group.acquisition_strategy, 0)
        new_priority = STRATEGY_PRIORITY.get(record.acquisition_strategy, 0)
        should_promote = False
        if new_priority > current_priority:
            should_promote = True
        elif new_priority == current_priority and CONFIDENCE_ORDER.get(record.confidence_score, 0) > CONFIDENCE_ORDER.get(
            group.best_confidence, 0
        ):
            should_promote = True
        if should_promote:
            group.best_confidence = record.confidence_score
            group.repo_url = record.repo_url
            group.normalized_url = record.normalized_url
            group.acquisition_strategy = record.acquisition_strategy
            group.artifact_type = record.artifact_type
            group.classification_reason = record.classification_reason
            group.normalized_repo_url = record.normalized_repo_url
        group.challenge_ids.add(record.challenge_id)
        if record.title:
            group.titles.add(record.title)
        group.records.append(record)
        group.candidate_urls.add(record.candidate_url)
    groups = sorted(
        by_key.values(),
        key=lambda g: (-CONFIDENCE_ORDER.get(g.best_confidence, 0), g.normalized_repo_key),
    )
    if max_repos is not None:
        groups = groups[:max_repos]
    return groups


class GitCommandError(RuntimeError):
    pass


class ArchiveAcquisitionError(RuntimeError):
    pass


def run_git(args: Sequence[str], cwd: Optional[Path] = None, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = ["git", *args]
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result
    except subprocess.CalledProcessError as exc:
        raise GitCommandError(exc.stderr.strip() or exc.stdout.strip() or str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCommandError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    except OSError as exc:
        raise GitCommandError(str(exc)) from exc


def detect_license(repo_path: Path) -> Optional[str]:
    for name in LICENSE_FILENAMES:
        candidate = repo_path / name
        if candidate.exists():
            try:
                with candidate.open("r", encoding="utf-8", errors="ignore") as handle:
                    first_line = handle.readline().strip()
                    if first_line:
                        return f"{name}:{first_line[:80]}"
                return f"{name}:present"
            except OSError:
                return f"{name}:unreadable"
    return None


def _ensure_safe_extract_path(dest: Path, target: Path) -> None:
    dest_resolved = dest.resolve()
    target_resolved = target.resolve()
    if not str(target_resolved).startswith(str(dest_resolved)):
        raise ArchiveAcquisitionError(f"unsafe_archive_path:{target}")


def _extract_zip(archive_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive_path) as zip_handle:
        for member in zip_handle.infolist():
            extracted = dest / member.filename
            _ensure_safe_extract_path(dest, extracted)
        zip_handle.extractall(dest)


def _extract_tar(archive_path: Path, dest: Path) -> None:
    with tarfile.open(archive_path) as tar_handle:
        for member in tar_handle.getmembers():
            member_path = dest / member.name
            _ensure_safe_extract_path(dest, member_path)
        tar_handle.extractall(dest)


def download_and_unpack_archive(source_url: str, dest: Path, timeout: int) -> str:
    tmp_dir = Path(tempfile.mkdtemp(prefix="topcoder-archive-"))
    tmp_file = tmp_dir / "archive.bin"
    sha256 = hashlib.sha256()
    try:
        with urlrequest.urlopen(source_url, timeout=timeout) as response, tmp_file.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                sha256.update(chunk)
    except (urlerror.HTTPError, urlerror.URLError, TimeoutError) as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ArchiveAcquisitionError(f"archive_download_failed:{exc}") from exc
    digest = sha256.hexdigest()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(tmp_file):
            _extract_zip(tmp_file, dest)
        elif tarfile.is_tarfile(tmp_file):
            _extract_tar(tmp_file, dest)
        else:
            raise ArchiveAcquisitionError("unsupported_archive_format")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return digest


def derive_archive_urls(group: RepoCandidateGroup) -> List[str]:
    urls: List[str] = []
    base_url = group.normalized_repo_url or group.repo_url
    info = normalize_repo_url(base_url)
    if not info:
        return urls
    owner_repo = info.repo_path.split("/")
    if len(owner_repo) < 2:
        return urls
    owner, repo_name = owner_repo[0], owner_repo[1]
    host = info.repo_host
    if host == "github.com":
        for branch in ("main", "master"):
            urls.append(f"https://{host}/{owner}/{repo_name}/archive/refs/heads/{branch}.zip")
    elif host == "gitlab.com":
        for branch in ("main", "master"):
            urls.append(f"https://{host}/{owner}/{repo_name}/-/archive/{branch}/{repo_name}-{branch}.zip")
    elif host == "bitbucket.org":
        for branch in ("main", "master", "default"):
            urls.append(f"https://{host}/{owner}/{repo_name}/get/{branch}.zip")
    return urls



@dataclass(slots=True)
class RepoFetchResult:
    repo_url: str
    normalized_repo_key: str
    repo_host: str
    challenge_ids: List[str]
    acquisition_strategy: str
    artifact_type: str
    clone_status: str
    local_path: Optional[str]
    source_origin: Optional[str]
    source_url: Optional[str]
    candidate_urls: List[str]
    rejection_reason: Optional[str] = None
    rejection_details: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    default_branch: Optional[str] = None
    resolved_commit: Optional[str] = None
    fetch_timestamp: Optional[str] = None
    license_info: Optional[str] = None
    archive_hash: Optional[str] = None


def ensure_repo(
    repo_url: str,
    dest: Path,
    timeout: int,
    retries: int,
    validate_remote: bool = True,
    shallow: bool = True,
) -> Tuple[str, Optional[str], Optional[str]]:
    attempt = 0
    last_error = ""
    while attempt <= retries:
        try:
            if dest.exists() and (dest / ".git").exists():
                fetch_args = ["fetch", "--all", "--prune"]
                if shallow:
                    fetch_args = ["fetch", "--depth", "1", "--all", "--prune"]
                run_git(fetch_args, cwd=dest, timeout=timeout)
                status = "updated"
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if validate_remote:
                    run_git(["ls-remote", repo_url], timeout=timeout)
                clone_args = ["clone"]
                if shallow:
                    clone_args.extend(["--depth", "1", "--no-tags", "--single-branch"])
                clone_args.extend([repo_url, str(dest)])
                run_git(clone_args, cwd=dest.parent, timeout=timeout)
                status = "cloned"
            if not dest.exists():
                raise GitCommandError(f"repo_path_missing:{dest}")
            branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest, timeout=timeout).stdout.strip()
            commit = run_git(["rev-parse", "HEAD"], cwd=dest, timeout=timeout).stdout.strip()
            return status, branch, commit
        except GitCommandError as exc:
            last_error = str(exc)
        attempt += 1
        time.sleep(min(2**attempt, 30))
    raise GitCommandError(last_error)


def build_fetch_result(
    group: RepoCandidateGroup,
    repo_root: Path,
    dry_run: bool,
    timeout: int,
    retries: int,
    prefer_archive_fallback: bool = False,
) -> RepoFetchResult:
    dest = repo_storage_path(repo_root, group.normalized_repo_key)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    candidate_urls = sorted(group.candidate_urls) if group.candidate_urls else [group.repo_url]
    if dry_run:
        return RepoFetchResult(
            repo_url=group.repo_url,
            normalized_repo_key=group.normalized_repo_key,
            repo_host=group.repo_host,
            challenge_ids=sorted(group.challenge_ids),
            acquisition_strategy=group.acquisition_strategy,
            artifact_type=group.artifact_type,
            clone_status="dry_run",
            local_path=str(dest),
            source_origin=None,
            source_url=group.repo_url,
            candidate_urls=candidate_urls,
            fetch_timestamp=timestamp,
        )

    def _make_result(
        status: str,
        source_origin: Optional[str],
        local_path: Optional[Path],
        source_url: Optional[str],
        default_branch: Optional[str] = None,
        resolved_commit: Optional[str] = None,
        license_info_value: Optional[str] = None,
        archive_hash: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        rejection_details: Optional[str] = None,
    ) -> RepoFetchResult:
        return RepoFetchResult(
            repo_url=group.repo_url,
            normalized_repo_key=group.normalized_repo_key,
            repo_host=group.repo_host,
            challenge_ids=sorted(group.challenge_ids),
            acquisition_strategy=group.acquisition_strategy,
            artifact_type=group.artifact_type,
            clone_status=status,
            local_path=str(local_path) if local_path else None,
            source_origin=source_origin,
            source_url=source_url,
            candidate_urls=candidate_urls,
            rejection_reason=rejection_reason,
            rejection_details=rejection_details,
            error_type=error_type,
            error_message=error_message,
            default_branch=default_branch,
            resolved_commit=resolved_commit,
            fetch_timestamp=timestamp,
            license_info=license_info_value,
            archive_hash=archive_hash,
        )

    if group.acquisition_strategy == "download_archive":
        try:
            archive_hash = download_and_unpack_archive(group.repo_url, dest, timeout=timeout)
            license_info = detect_license(dest)
            return _make_result(
                status="archive_downloaded",
                source_origin="archive",
                local_path=dest,
                source_url=group.repo_url,
                license_info_value=license_info,
                archive_hash=archive_hash,
            )
        except ArchiveAcquisitionError as exc:
            return _make_result(
                status="failed",
                source_origin="archive",
                local_path=dest,
                source_url=group.repo_url,
                error_type="archive_error",
                error_message=str(exc),
            )
    try:
        status, branch, commit = ensure_repo(group.repo_url, dest, timeout=timeout, retries=retries)
        license_info = detect_license(dest)
        return _make_result(
            status=status,
            source_origin="clone",
            local_path=dest,
            source_url=group.repo_url,
            default_branch=branch,
            resolved_commit=commit,
            license_info_value=license_info,
        )
    except GitCommandError as exc:
        error_message = str(exc)
        if group.acquisition_strategy == "clone_or_source_download" and prefer_archive_fallback:
            derived_archives = derive_archive_urls(group)
            for archive_url in derived_archives:
                try:
                    archive_hash = download_and_unpack_archive(archive_url, dest, timeout=timeout)
                    license_info = detect_license(dest)
                    return _make_result(
                        status="archive_downloaded",
                        source_origin="archive",
                        local_path=dest,
                        source_url=archive_url,
                        license_info_value=license_info,
                        archive_hash=archive_hash,
                    )
                except ArchiveAcquisitionError as archive_exc:
                    error_message = str(archive_exc)
        return _make_result(
            status="failed",
            source_origin="clone",
            local_path=dest if dest.exists() else None,
            source_url=group.repo_url,
            error_type="git_error",
            error_message=error_message,
        )

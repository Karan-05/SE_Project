"""Discovery helpers for the public repository acquisition pipeline."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .github_client import GitHubClient, GitHubClientError
from .scoring import compute_suitability
from .types import RepoCandidate, RepoIdentity, merge_candidate_lists
from .utils import iter_json_records, normalize_language, now_utc_iso, parse_repo_url

BENCHMARK_MANIFEST_CANDIDATES = [
    Path("data/cgcs/all_rows.jsonl"),
    Path("data/cgcs/train.jsonl"),
    Path("data/cgcs/dev.jsonl"),
    Path("data/cgcs/test.jsonl"),
]

BUILD_FILE_HINTS = {
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "pipfile",
    "poetry.lock",
    "makefile",
    "build.gradle",
    "build.gradle.kts",
    "gradlew",
    "pom.xml",
    "tsconfig.json",
}

TEST_DIR_HINTS = {"tests", "test", "testing", "__tests__", "spec", "specs"}
TEST_FILE_HINTS = {"pytest.ini", "tox.ini", "jest.config.js", "jest.config.ts", "karma.conf.js"}
CI_FILE_HINTS = {
    ".github/workflows",
    ".circleci",
    ".gitlab-ci.yml",
    ".travis.yml",
    "azure-pipelines.yml",
}
LICENSE_HINTS = {"license", "license.md", "license.txt", "copying", "copyright"}


@dataclass(slots=True)
class DiscoveryConfig:
    sources: set[str]
    min_stars: int
    target_size: int
    languages: list[str]
    recent_days: int
    max_per_owner: int
    seed: int


def _owner_key(identity: RepoIdentity) -> str:
    return f"{identity.host.lower()}/{identity.owner.lower()}"


def _extract_repo_identity(record: dict[str, object]) -> RepoIdentity | None:
    candidate_fields = (
        "repo_url",
        "repository_url",
        "repo",
        "repo_full_name",
        "repo_name",
        "repository",
        "html_url",
        "project_url",
        "source_repo",
        "git_repo",
    )
    for field in candidate_fields:
        value = record.get(field)
        if not value:
            continue
        identity = _parse_identity_value(value)
        if identity:
            return identity
    owner_keys = ("repo_owner", "repoOwner", "organization", "owner")
    repo_keys = ("repo_name", "repoName", "repository", "name")
    for owner_key in owner_keys:
        owner_value = record.get(owner_key)
        if not owner_value:
            continue
        for repo_key in repo_keys:
            repo_value = record.get(repo_key)
            if repo_value:
                identity = parse_repo_url(f"{owner_value}/{repo_value}")
                if identity:
                    return identity
    nested = record.get("repo_metadata") or record.get("repository_metadata")
    if isinstance(nested, dict):
        identity = _extract_repo_identity(nested)
        if identity:
            return identity
    return None


def _parse_identity_value(value: object) -> RepoIdentity | None:
    if isinstance(value, dict):
        for key in ("full_name", "repo_full_name", "slug"):
            nested = value.get(key)
            if nested:
                identity = parse_repo_url(str(nested))
                if identity:
                    return identity
        owner = value.get("owner") or value.get("organization")
        name = value.get("name") or value.get("repo_name")
        if isinstance(owner, dict):
            owner = owner.get("login") or owner.get("name")
        if owner and name:
            return parse_repo_url(f"{owner}/{name}")
        for key in ("url", "html_url", "clone_url", "git_url"):
            nested = value.get(key)
            if nested:
                identity = parse_repo_url(str(nested))
                if identity:
                    return identity
        return None
    if isinstance(value, str):
        return parse_repo_url(value)
    return None


def load_benchmark_seed_candidates(
    manifests: Sequence[Path],
    max_per_owner: int,
    owner_counts: dict[str, int],
) -> list[RepoCandidate]:
    candidates: list[RepoCandidate] = []
    seen: set[str] = set()
    for manifest in manifests:
        if not manifest.exists():
            continue
        for record in iter_json_records(manifest):
            identity = _extract_repo_identity(record)
            if not identity:
                continue
            key = identity.repo_key
            if key in seen:
                continue
            owner_key = _owner_key(identity)
            if max_per_owner > 0 and owner_counts.get(owner_key, 0) >= max_per_owner:
                continue
            owner_counts[owner_key] = owner_counts.get(owner_key, 0) + 1
            seen.add(key)
            candidates.append(RepoCandidate.from_identity(identity, "benchmark_seed"))
    return candidates


def _describe_entry(entry: dict[str, object]) -> str:
    name = str(entry.get("name") or "")
    return name or ""


def detect_repo_signals(client: GitHubClient, candidate: RepoCandidate) -> None:
    if candidate.host != "github.com":
        return
    try:
        entries = client.list_directory(candidate.owner, candidate.name)
    except GitHubClientError:
        return
    build_files: list[str] = []
    test_hits: list[str] = []
    ci_hits: list[str] = []
    has_license = candidate.has_license
    entry_lookup = {str(entry.get("name") or "").lower(): entry for entry in entries}
    for entry in entries:
        entry_type = str(entry.get("type") or "")
        name = str(entry.get("name") or "")
        lower_name = name.lower()
        if entry_type == "file":
            if lower_name in BUILD_FILE_HINTS:
                build_files.append(name)
            if lower_name in TEST_FILE_HINTS:
                test_hits.append(name)
            if lower_name in LICENSE_HINTS:
                has_license = True
            if lower_name in CI_FILE_HINTS:
                ci_hits.append(name)
        elif entry_type == "dir":
            if lower_name in TEST_DIR_HINTS:
                test_hits.append(name)
            if lower_name == ".circleci":
                ci_hits.append(name)
            if lower_name == ".github":
                workflows = client.list_directory(candidate.owner, candidate.name, ".github/workflows")
                if workflows:
                    ci_hits.append(".github/workflows")
    candidate.has_build_files = bool(build_files)
    candidate.detected_build_files = sorted(build_files)
    candidate.has_tests = bool(test_hits)
    candidate.detected_test_files = sorted(test_hits)
    candidate.has_ci = bool(ci_hits)
    candidate.ci_config_paths = sorted({hit for hit in ci_hits})
    candidate.has_license = has_license


def enrich_github_metadata(client: GitHubClient, candidate: RepoCandidate) -> RepoCandidate:
    if candidate.host != "github.com":
        candidate.exclusion_reasons.append("unsupported_host")
        return candidate
    try:
        repo_info = client.get_repo(candidate.owner, candidate.name)
    except GitHubClientError as exc:
        candidate.exclusion_reasons.append(f"github_error:{exc}")
        return candidate
    candidate.description = repo_info.get("description")
    candidate.language = repo_info.get("language")
    candidate.topics = repo_info.get("topics") or []
    candidate.stars = int(repo_info.get("stargazers_count") or 0)
    candidate.forks = int(repo_info.get("forks_count") or 0)
    candidate.watchers = int(repo_info.get("subscribers_count") or repo_info.get("watchers_count") or 0)
    candidate.last_pushed_at = repo_info.get("pushed_at")
    candidate.archived = bool(repo_info.get("archived", False))
    candidate.default_branch = repo_info.get("default_branch")
    candidate.has_license = candidate.has_license or bool(repo_info.get("license"))
    candidate.estimated_size_kb = repo_info.get("size")
    detect_repo_signals(client, candidate)
    return candidate


def collect_search_candidates(
    client: GitHubClient,
    config: DiscoveryConfig,
    owner_counts: dict[str, int],
) -> list[RepoCandidate]:
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=config.recent_days)).date().isoformat()
    results: list[RepoCandidate] = []
    seen_keys: set[str] = set()
    languages = config.languages or ["python"]
    # Distribute the target evenly across languages so no single language
    # monopolises the candidate pool before others are queried.
    per_language_cap = max(1, config.target_size // len(languages))
    for language in languages:
        language_count = 0
        query = f"language:{language} stars:>={config.min_stars} pushed:>={cutoff_date} archived:false"
        for repo in client.search_repositories(query, per_page=100, max_pages=10):
            identity = parse_repo_url(str(repo.get("html_url") or repo.get("full_name") or ""))
            if not identity:
                continue
            key = identity.repo_key
            if key in seen_keys:
                continue
            owner_key = _owner_key(identity)
            if config.max_per_owner > 0 and owner_counts.get(owner_key, 0) >= config.max_per_owner:
                continue
            seen_keys.add(key)
            owner_counts[owner_key] = owner_counts.get(owner_key, 0) + 1
            candidate = RepoCandidate.from_identity(identity, "host_search")
            candidate.language = repo.get("language")
            candidate.stars = int(repo.get("stargazers_count") or 0)
            candidate.forks = int(repo.get("forks_count") or 0)
            candidate.watchers = int(repo.get("watchers_count") or 0)
            candidate.last_pushed_at = repo.get("pushed_at")
            candidate.archived = bool(repo.get("archived", False))
            candidate.description = repo.get("description")
            candidate.estimated_size_kb = repo.get("size")
            results.append(candidate)
            language_count += 1
            if language_count >= per_language_cap:
                break
    return results


def discover_public_repo_candidates(
    client: GitHubClient,
    config: DiscoveryConfig,
    benchmark_manifests: Sequence[Path],
) -> tuple[list[RepoCandidate], dict[str, object]]:
    owner_counts: dict[str, int] = defaultdict(int)
    seed_candidates: list[RepoCandidate] = []
    if "benchmark_seed" in config.sources:
        seed_candidates = load_benchmark_seed_candidates(benchmark_manifests, config.max_per_owner, owner_counts)
    search_candidates: list[RepoCandidate] = []
    if "github_search" in config.sources:
        search_candidates = collect_search_candidates(client, config, owner_counts)
    merged_candidates = merge_candidate_lists([*search_candidates, *seed_candidates])
    enriched: list[RepoCandidate] = []
    for candidate in merged_candidates.values():
        enriched.append(enrich_github_metadata(client, candidate))
    rng = random.Random(config.seed)
    rng.shuffle(enriched)
    for candidate in enriched:
        compute_suitability(candidate, config.min_stars, config.recent_days)
    enriched.sort(key=lambda c: (-c.suitability_score, c.repo_key))
    summary = build_discovery_summary(enriched, config)
    return enriched, summary


def build_discovery_summary(candidates: Sequence[RepoCandidate], config: DiscoveryConfig) -> dict[str, object]:
    language_counts = Counter(normalize_language(candidate.language) for candidate in candidates)
    source_counts = Counter()
    host_counts = Counter()
    archived = 0
    for candidate in candidates:
        host_counts[candidate.host] += 1
        tags = candidate.source_tags or []
        unique_tags = {candidate.source_type} if candidate.source_type else set()
        unique_tags.update(tags)
        for tag in unique_tags:
            if tag:
                source_counts[tag] += 1
        if candidate.archived:
            archived += 1
    exclusion_counts = Counter(reason for candidate in candidates for reason in candidate.exclusion_reasons)
    score_values = [candidate.suitability_score for candidate in candidates]
    summary = {
        "generated_at": now_utc_iso(),
        "total_candidates": len(candidates),
        "archived_candidates": archived,
        "sources": dict(source_counts),
        "hosts": dict(host_counts),
        "languages": dict(language_counts),
        "scores": {
            "min": min(score_values) if score_values else 0,
            "max": max(score_values) if score_values else 0,
            "avg": sum(score_values) / len(score_values) if score_values else 0,
        },
        "exclusion_reasons": dict(exclusion_counts),
        "config": {
            "min_stars": config.min_stars,
            "target_size": config.target_size,
            "languages": config.languages,
            "recent_days": config.recent_days,
            "max_per_owner": config.max_per_owner,
            "sources": sorted(config.sources),
        },
    }
    return summary

"""Shared dataclasses for the public repository acquisition pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


def _normalize_fragment(value: str) -> str:
    return value.strip().strip("/").lower()


def make_repo_key(host: str, owner: str, name: str) -> str:
    """Return a normalized repository key."""

    fragments = (_normalize_fragment(host), _normalize_fragment(owner), _normalize_fragment(name))
    return "/".join(fragments)


@dataclass(slots=True)
class RepoIdentity:
    """Normalized reference to a repository."""

    host: str
    owner: str
    name: str

    @property
    def repo_key(self) -> str:
        return make_repo_key(self.host, self.owner, self.name)

    @property
    def repo_url(self) -> str:
        return f"https://{self.host}/{self.owner}/{self.name}"


@dataclass(slots=True)
class RepoCandidate:
    """Full set of metadata captured during discovery."""

    host: str
    owner: str
    name: str
    source_type: str
    repo_url: str
    source_tags: list[str] = field(default_factory=list)
    description: str | None = None
    language: str | None = None
    topics: list[str] = field(default_factory=list)
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    last_pushed_at: str | None = None
    archived: bool = False
    default_branch: str | None = None
    has_license: bool = False
    has_ci: bool = False
    ci_config_paths: list[str] = field(default_factory=list)
    has_build_files: bool = False
    has_tests: bool = False
    detected_build_files: list[str] = field(default_factory=list)
    detected_test_files: list[str] = field(default_factory=list)
    estimated_size_kb: int | None = None
    suitability_score: float = 0.0
    suitability_reasons: list[str] = field(default_factory=list)
    exclusion_reasons: list[str] = field(default_factory=list)
    selection_rank: int | None = None

    @property
    def repo_key(self) -> str:
        return make_repo_key(self.host, self.owner, self.name)

    def add_source_tag(self, source: str) -> None:
        if source not in self.source_tags:
            self.source_tags.append(source)

    def as_dict(self) -> dict[str, object]:
        return {
            "repo_url": self.repo_url,
            "repo_key": self.repo_key,
            "host": self.host,
            "owner": self.owner,
            "name": self.name,
            "source_type": self.source_type,
            "source_tags": self.source_tags,
            "description": self.description,
            "language": self.language,
            "topics": self.topics,
            "stars": self.stars,
            "forks": self.forks,
            "watchers": self.watchers,
            "last_pushed_at": self.last_pushed_at,
            "archived": self.archived,
            "default_branch": self.default_branch,
            "has_license": self.has_license,
            "has_ci": self.has_ci,
            "ci_config_paths": self.ci_config_paths,
            "has_build_files": self.has_build_files,
            "has_tests": self.has_tests,
            "detected_build_files": self.detected_build_files,
            "detected_test_files": self.detected_test_files,
            "estimated_size_kb": self.estimated_size_kb,
            "suitability_score": round(self.suitability_score, 4),
            "suitability_reasons": self.suitability_reasons,
            "exclusion_reasons": self.exclusion_reasons,
            "selection_rank": self.selection_rank,
        }

    @classmethod
    def from_identity(cls, identity: RepoIdentity, source_type: str) -> "RepoCandidate":
        return cls(
            host=identity.host,
            owner=identity.owner,
            name=identity.name,
            source_type=source_type,
            repo_url=identity.repo_url,
            source_tags=[source_type],
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "RepoCandidate":
        estimated_size_value = payload.get("estimated_size_kb")
        estimated_size_kb = None
        if isinstance(estimated_size_value, (int, float)):
            estimated_size_kb = int(estimated_size_value)
        elif isinstance(estimated_size_value, str):
            try:
                estimated_size_kb = int(float(estimated_size_value))
            except ValueError:
                estimated_size_kb = None
        candidate = cls(
            host=str(payload.get("host") or ""),
            owner=str(payload.get("owner") or ""),
            name=str(payload.get("name") or ""),
            source_type=str(payload.get("source_type") or payload.get("primary_source") or "unknown"),
            repo_url=str(payload.get("repo_url") or ""),
            source_tags=list(payload.get("source_tags") or []),
            description=payload.get("description"),
            language=payload.get("language"),
            topics=list(payload.get("topics") or []),
            stars=int(payload.get("stars") or 0),
            forks=int(payload.get("forks") or 0),
            watchers=int(payload.get("watchers") or 0),
            last_pushed_at=str(payload.get("last_pushed_at") or "") or None,
            archived=bool(payload.get("archived", False)),
            default_branch=payload.get("default_branch"),
            has_license=bool(payload.get("has_license", False)),
            has_ci=bool(payload.get("has_ci", False)),
            ci_config_paths=list(payload.get("ci_config_paths") or []),
            has_build_files=bool(payload.get("has_build_files", False)),
            has_tests=bool(payload.get("has_tests", False)),
            detected_build_files=list(payload.get("detected_build_files") or []),
            detected_test_files=list(payload.get("detected_test_files") or []),
            estimated_size_kb=estimated_size_kb,
            suitability_score=float(payload.get("suitability_score") or 0.0),
            suitability_reasons=list(payload.get("suitability_reasons") or []),
            exclusion_reasons=list(payload.get("exclusion_reasons") or []),
            selection_rank=payload.get("selection_rank"),
        )
        return candidate


def merge_candidate_lists(groups: Iterable[RepoCandidate]) -> dict[str, RepoCandidate]:
    """Return a mapping of repo_key->candidate where later entries add source tags."""

    merged: dict[str, RepoCandidate] = {}
    for candidate in groups:
        record = merged.get(candidate.repo_key)
        if record is None:
            merged[candidate.repo_key] = candidate
            continue
        record.add_source_tag(candidate.source_type)
        for tag in candidate.source_tags:
            record.add_source_tag(tag)
    return merged

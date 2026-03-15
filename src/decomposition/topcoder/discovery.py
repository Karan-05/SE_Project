"""Discovery utilities for locating Topcoder artifact and repo candidates."""

from __future__ import annotations

import csv
import gzip
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from . import CONFIDENCE_ORDER
from .artifact_classifier import ArtifactClassification, REPO_ACQUISITION_STRATEGIES, classify_candidate_url
from .repos import confidence_allows

URL_PATTERN = re.compile(r"(https?://[^\s)]+|git@[A-Za-z0-9_.:/-]+)")

REPO_FIELD_CANDIDATES = (
    "repo_url",
    "repoUrl",
    "gitRepoUrl",
    "githubRepoUrl",
    "taskRepoUrl",
    "repositoryUrl",
    "sourceRepoUrl",
    "codeRepoUrl",
    "repo",
    "repository",
    "git_repository",
    "repoLink",
)

TEXT_FIELD_HINTS = (
    "description",
    "detailedRequirements",
    "detailed_requirements",
    "detailedRequirementsMarkdown",
    "overview",
    "body",
    "instructions",
    "specification",
    "submissionGuidelines",
    "challengeOverview",
    "challengeDescription",
    "requirements",
    "notes",
)


@dataclass(slots=True)
class ChallengeRecord:
    challenge_id: str
    title: str
    description: str
    payload: Dict[str, object]
    source_path: str


@dataclass(slots=True)
class ArtifactCandidate:
    challenge_id: str
    title: str
    candidate_url: str
    normalized_url: str
    host: str
    path: str
    source_path: str
    source_field: str
    discovery_method: str
    evidence_snippet: str
    artifact_type: str
    acquisition_strategy: str
    confidence_score: str
    classification_reason: str
    normalized_repo_key: Optional[str]
    normalized_repo_url: Optional[str]
    challenge_text_context: str
    notes: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "challenge_id": self.challenge_id,
            "title": self.title,
            "candidate_url": self.candidate_url,
            "normalized_url": self.normalized_url,
            "host": self.host,
            "path": self.path,
            "source_path": self.source_path,
            "source_field": self.source_field,
            "discovery_method": self.discovery_method,
            "evidence_snippet": self.evidence_snippet,
            "artifact_type": self.artifact_type,
            "acquisition_strategy": self.acquisition_strategy,
            "confidence_score": self.confidence_score,
            "classification_reason": self.classification_reason,
            "normalized_repo_key": self.normalized_repo_key,
            "normalized_repo_url": self.normalized_repo_url,
            "challenge_text_context": self.challenge_text_context,
            "notes": self.notes,
        }


@dataclass(slots=True)
class ArtifactDiscoverySummary:
    records_scanned: int = 0
    artifact_candidates_emitted: int = 0
    by_artifact_type: Dict[str, int] = field(default_factory=dict)
    by_host: Dict[str, int] = field(default_factory=dict)
    by_strategy: Dict[str, int] = field(default_factory=dict)
    discovery_methods: Dict[str, int] = field(default_factory=dict)
    source_files: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "records_scanned": self.records_scanned,
            "artifact_candidates_emitted": self.artifact_candidates_emitted,
            "by_artifact_type": self.by_artifact_type,
            "by_host": self.by_host,
            "by_strategy": self.by_strategy,
            "discovery_methods": self.discovery_methods,
            "source_files": self.source_files,
        }


@dataclass(slots=True)
class RepoCandidate:
    challenge_id: str
    title: str
    candidate_url: str
    repo_url: str
    normalized_url: str
    repo_host: str
    source_field: str
    discovery_method: str
    confidence_score: str
    evidence_snippet: str
    normalized_repo_key: str
    is_duplicate_candidate: bool
    notes: str
    artifact_type: str
    acquisition_strategy: str
    classification_reason: str
    challenge_text_context: str
    normalized_repo_url: Optional[str] = None
    discovered_repo_candidate: bool = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "challenge_id": self.challenge_id,
            "title": self.title,
            "candidate_url": self.candidate_url,
            "repo_url": self.repo_url,
            "normalized_url": self.normalized_url,
            "repo_host": self.repo_host,
            "source_field": self.source_field,
            "discovery_method": self.discovery_method,
            "confidence_score": self.confidence_score,
            "evidence_snippet": self.evidence_snippet,
            "normalized_repo_key": self.normalized_repo_key,
            "is_duplicate_candidate": self.is_duplicate_candidate,
            "notes": self.notes,
            "artifact_type": self.artifact_type,
            "acquisition_strategy": self.acquisition_strategy,
            "classification_reason": self.classification_reason,
            "challenge_text_context": self.challenge_text_context,
            "normalized_repo_url": self.normalized_repo_url,
            "discovered_repo_candidate": self.discovered_repo_candidate,
        }


@dataclass(slots=True)
class RepoDiscoverySummary:
    artifact_candidates_input: int = 0
    repo_candidates_emitted: int = 0
    unique_repo_count: int = 0
    by_confidence: Dict[str, int] = field(default_factory=dict)
    by_host: Dict[str, int] = field(default_factory=dict)
    by_strategy: Dict[str, int] = field(default_factory=dict)
    by_artifact_type: Dict[str, int] = field(default_factory=dict)
    min_confidence: str = "low"

    def to_dict(self) -> Dict[str, object]:
        return {
            "artifact_candidates_input": self.artifact_candidates_input,
            "repo_candidates_emitted": self.repo_candidates_emitted,
            "unique_repo_count": self.unique_repo_count,
            "by_confidence": self.by_confidence,
            "by_host": self.by_host,
            "by_strategy": self.by_strategy,
            "by_artifact_type": self.by_artifact_type,
            "min_confidence": self.min_confidence,
        }


def _iter_lines(handle: Iterable[str]) -> Iterator[str]:
    for line in handle:
        line = line.strip()
        if line:
            yield line


def read_tasks_csv(path: Path) -> Iterator[ChallengeRecord]:
    if not path or not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            challenge_id = str(row.get("task_id") or row.get("challenge_id") or "").strip()
            if not challenge_id:
                continue
            yield ChallengeRecord(
                challenge_id=challenge_id,
                title=str(row.get("title") or "").strip(),
                description=str(row.get("description") or "").strip(),
                payload=dict(row),
                source_path=str(path),
            )


def _load_json_blob(text: str) -> Sequence[object]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        records: List[object] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        if "data" in loaded and isinstance(loaded["data"], list):
            return loaded["data"]
        if "items" in loaded and isinstance(loaded["items"], list):
            return loaded["items"]
        return [loaded]
    return [loaded]


def read_json_records(path: Path) -> Iterator[ChallengeRecord]:
    if not path.exists():
        return
    opener = gzip.open if path.suffix.endswith("gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        payloads = _load_json_blob(handle.read())
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        challenge_id = str(
            payload.get("id")
            or payload.get("challenge_id")
            or payload.get("task_id")
            or payload.get("legacyId")
            or "",
        ).strip()
        if not challenge_id:
            continue
        title = str(payload.get("title") or payload.get("name") or "").strip()
        description = str(
            payload.get("description")
            or payload.get("detailedRequirements")
            or payload.get("overview")
            or "",
        ).strip()
        yield ChallengeRecord(
            challenge_id=challenge_id,
            title=title,
            description=description,
            payload=payload,
            source_path=str(path),
        )


def iter_all_records(
    tasks_csv: Optional[Path],
    page_globs: Sequence[str] | None,
    challenge_data_globs: Sequence[str] | None,
    corpus_index: Optional[Path],
) -> Iterator[ChallengeRecord]:
    if tasks_csv:
        yield from read_tasks_csv(tasks_csv)
    for glob_pattern in page_globs or []:
        for path in sorted(Path().glob(glob_pattern)):
            yield from read_json_records(path)
    for glob_pattern in challenge_data_globs or []:
        for path in sorted(Path().glob(glob_pattern)):
            yield from read_json_records(path)
    if corpus_index and corpus_index.exists():
        with corpus_index.open("r", encoding="utf-8") as handle:
            for line in _iter_lines(handle):
                payload = json.loads(line)
                challenge_id = str(payload.get("challenge_id") or payload.get("task_id") or "").strip()
                if not challenge_id:
                    continue
                yield ChallengeRecord(
                    challenge_id=challenge_id,
                    title=str(payload.get("title") or "").strip(),
                    description=str(payload.get("description") or "").strip(),
                    payload=payload,
                    source_path=str(corpus_index),
                )


def extract_urls_from_text(text: str) -> Iterator[str]:
    if not text:
        return
    for match in URL_PATTERN.finditer(text):
        yield match.group(0).strip(".,)")


def _confidence_for(field_name: str, method: str) -> str:
    if field_name in REPO_FIELD_CANDIDATES or method == "explicit_field":
        return "high"
    if method == "attachment":
        return "medium"
    return "low"


def _combine_confidence(*values: str) -> str:
    best = "low"
    for value in values:
        if CONFIDENCE_ORDER.get(value, 0) > CONFIDENCE_ORDER.get(best, 0):
            best = value
    return best


def _evidence_snippet(text: str, needle: str) -> str:
    text = text or ""
    idx = text.lower().find(needle.lower())
    if idx == -1:
        return text[:200]
    start = max(idx - 60, 0)
    end = min(idx + len(needle) + 60, len(text))
    return text[start:end]


def _candidate_from_value(
    record: ChallengeRecord,
    value: str,
    field_name: str,
    method: str,
    notes: str,
    raw_field: str,
) -> List[ArtifactCandidate]:
    candidates: List[ArtifactCandidate] = []
    if not value:
        return candidates
    urls = list(extract_urls_from_text(value))
    if not urls:
        return candidates
    base_confidence = _confidence_for(raw_field, method)
    context = record.description[:280]
    for url in urls:
        classification: ArtifactClassification = classify_candidate_url(url)
        confidence = _combine_confidence(base_confidence, classification.confidence)
        evidence = _evidence_snippet(value, url)
        candidates.append(
            ArtifactCandidate(
                challenge_id=record.challenge_id,
                title=record.title,
                candidate_url=url,
                normalized_url=classification.normalized_url,
                host=classification.host,
                path=classification.path,
                source_path=record.source_path,
                source_field=field_name,
                discovery_method=method,
                evidence_snippet=evidence,
                artifact_type=classification.artifact_type,
                acquisition_strategy=classification.acquisition_strategy,
                confidence_score=confidence,
                classification_reason=classification.classification_reason,
                normalized_repo_key=classification.normalized_repo_key,
                normalized_repo_url=classification.normalized_repo_url,
                challenge_text_context=context,
                notes=notes,
            )
        )
    return candidates


def _iter_attachment_values(payload: Dict[str, object]) -> Iterator[Tuple[str, str]]:
    attachments = payload.get("attachments") or payload.get("challengeAttachments")
    if isinstance(attachments, list):
        for idx, item in enumerate(attachments):
            if isinstance(item, dict):
                for key in ("downloadUrl", "url", "filePath", "fileURL", "fileUrl"):
                    value = item.get(key)
                    if isinstance(value, str):
                        yield (f"attachments[{idx}].{key}", value)
            elif isinstance(item, str):
                yield (f"attachments[{idx}]", item)


def discover_candidates_from_record(record: ChallengeRecord) -> List[ArtifactCandidate]:
    payload = record.payload
    candidates: List[ArtifactCandidate] = []
    for field in REPO_FIELD_CANDIDATES:
        value = payload.get(field)
        if isinstance(value, str):
            candidates.extend(
                _candidate_from_value(
                    record,
                    value,
                    f"{record.source_path}:{field}",
                    "explicit_field",
                    "direct_repo_field",
                    raw_field=field,
                )
            )
    for field in TEXT_FIELD_HINTS:
        value = payload.get(field)
        if isinstance(value, str):
            candidates.extend(
                _candidate_from_value(
                    record,
                    value,
                    f"{record.source_path}:{field}",
                    "text_field",
                    "text_field_scan",
                    raw_field=field,
                )
            )
    for field_name, value in _iter_attachment_values(payload):
        candidates.extend(
            _candidate_from_value(
                record,
                value,
                f"{record.source_path}:{field_name}",
                "attachment",
                "attachment_link",
                raw_field="attachment",
            )
        )
    # fallback: description string from record
    candidates.extend(
        _candidate_from_value(
            record,
            record.description,
            f"{record.source_path}:description",
            "description",
            "record_description",
            raw_field="description",
        )
    )
    return candidates


def discover_artifact_candidates(records: Iterable[ChallengeRecord]) -> Tuple[List[ArtifactCandidate], ArtifactDiscoverySummary]:
    summary = ArtifactDiscoverySummary()
    artifacts: List[ArtifactCandidate] = []
    seen_sources: Dict[str, int] = {}
    for record in records:
        summary.records_scanned += 1
        seen_sources[record.source_path] = seen_sources.get(record.source_path, 0) + 1
        discovered = discover_candidates_from_record(record)
        artifacts.extend(discovered)
        for artifact in discovered:
            summary.artifact_candidates_emitted += 1
            summary.by_artifact_type[artifact.artifact_type] = (
                summary.by_artifact_type.get(artifact.artifact_type, 0) + 1
            )
            if artifact.host:
                summary.by_host[artifact.host] = summary.by_host.get(artifact.host, 0) + 1
            summary.by_strategy[artifact.acquisition_strategy] = (
                summary.by_strategy.get(artifact.acquisition_strategy, 0) + 1
            )
            summary.discovery_methods[artifact.discovery_method] = (
                summary.discovery_methods.get(artifact.discovery_method, 0) + 1
            )
    summary.source_files = seen_sources
    return artifacts, summary


def filter_repo_candidates(
    artifacts: Iterable[ArtifactCandidate],
    min_confidence: str = "low",
    allowed_strategies: Optional[Sequence[str]] = None,
) -> Tuple[List[RepoCandidate], RepoDiscoverySummary]:
    allowed = set(allowed_strategies or REPO_ACQUISITION_STRATEGIES)
    results: List[RepoCandidate] = []
    summary = RepoDiscoverySummary(min_confidence=min_confidence)
    unique_tracker: set[str] = set()
    for artifact in artifacts:
        summary.artifact_candidates_input += 1
        if artifact.acquisition_strategy not in allowed:
            continue
        if not artifact.normalized_repo_key:
            continue
        if not confidence_allows(artifact.confidence_score, min_confidence):
            continue
        normalized_key = artifact.normalized_repo_key
        duplicate = normalized_key in unique_tracker
        unique_tracker.add(normalized_key)
        summary.by_confidence[artifact.confidence_score] = (
            summary.by_confidence.get(artifact.confidence_score, 0) + 1
        )
        summary.by_host[artifact.host] = summary.by_host.get(artifact.host, 0) + 1
        summary.by_strategy[artifact.acquisition_strategy] = (
            summary.by_strategy.get(artifact.acquisition_strategy, 0) + 1
        )
        summary.by_artifact_type[artifact.artifact_type] = (
            summary.by_artifact_type.get(artifact.artifact_type, 0) + 1
        )
        summary.repo_candidates_emitted += 1
        repo_url = artifact.normalized_repo_url or artifact.normalized_url or artifact.candidate_url
        results.append(
            RepoCandidate(
                challenge_id=artifact.challenge_id,
                title=artifact.title,
                candidate_url=artifact.candidate_url,
                repo_url=repo_url,
                normalized_url=artifact.normalized_url,
                repo_host=artifact.host,
                source_field=artifact.source_field,
                discovery_method=artifact.discovery_method,
                confidence_score=artifact.confidence_score,
                evidence_snippet=artifact.evidence_snippet,
                normalized_repo_key=normalized_key,
                is_duplicate_candidate=duplicate,
                notes=artifact.notes,
                artifact_type=artifact.artifact_type,
                acquisition_strategy=artifact.acquisition_strategy,
                classification_reason=artifact.classification_reason,
                challenge_text_context=artifact.challenge_text_context,
                normalized_repo_url=artifact.normalized_repo_url,
            )
        )
    summary.unique_repo_count = len(unique_tracker)
    return results, summary


def discover_repo_candidates(records: Iterable[ChallengeRecord]) -> Tuple[List[RepoCandidate], RepoDiscoverySummary]:
    artifacts, _ = discover_artifact_candidates(records)
    return filter_repo_candidates(artifacts)

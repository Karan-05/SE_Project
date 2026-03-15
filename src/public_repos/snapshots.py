"""Inspect cloned repositories to generate build/test/language signals."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .utils import now_utc_iso, write_json, write_jsonl

IGNORED_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", "dist", "build", ".venv", "venv"}
LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
}
BUILD_SYSTEM_HINTS = {
    "package.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "package-lock.json": "npm",
    "pyproject.toml": "python-pyproject",
    "requirements.txt": "pip",
    "setup.py": "setuptools",
    "setup.cfg": "setuptools",
    "pipfile": "pipenv",
    "poetry.lock": "poetry",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "gradlew": "gradle",
    "pom.xml": "maven",
    "makefile": "make",
}
TEST_FILE_HINTS = {
    "pytest.ini": "pytest",
    "tox.ini": "tox",
    "jest.config.js": "jest",
    "jest.config.ts": "jest",
    "karma.conf.js": "karma",
    "package.json": "npm-test",
}


@dataclass(slots=True)
class RepoSnapshot:
    repo_key: str
    repo_url: str
    local_path: Path
    resolved_commit: str | None
    default_branch: str | None
    languages: list[str]
    language_counts: dict[str, int]
    build_systems: list[str]
    test_frameworks: list[str]
    detected_build_files: list[str]
    detected_test_paths: list[str]
    file_count: int
    has_tests: bool
    has_build_files: bool
    top_level_files: list[str]
    metadata: dict[str, object] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_utc_iso)

    def as_dict(self) -> dict[str, object]:
        payload = {
            "repo_key": self.repo_key,
            "repo_url": self.repo_url,
            "local_path": str(self.local_path),
            "resolved_commit": self.resolved_commit,
            "default_branch": self.default_branch,
            "languages": self.languages,
            "language_counts": self.language_counts,
            "build_systems": self.build_systems,
            "test_frameworks": self.test_frameworks,
            "detected_build_files": self.detected_build_files,
            "detected_test_paths": self.detected_test_paths,
            "file_count": self.file_count,
            "has_tests": self.has_tests,
            "has_build_files": self.has_build_files,
            "top_level_files": self.top_level_files,
            "timestamp": self.timestamp,
        }
        payload.update(self.metadata)
        return payload


def load_fetch_manifest(path: Path) -> list[dict[str, object]]:
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


def iter_repo_files(root: Path, max_files: int) -> Iterable[Path]:
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in IGNORED_DIRS]
        for filename in filenames:
            count += 1
            yield Path(dirpath) / filename
            if count >= max_files:
                return


def detect_repo_contents(repo_path: Path, max_files: int) -> dict[str, object]:
    language_counts: Counter = Counter()
    build_files: set[str] = set()
    test_paths: set[str] = set()
    build_systems: set[str] = set()
    test_frameworks: set[str] = set()
    file_count = 0
    top_level_files = sorted(
        [entry.name for entry in repo_path.iterdir() if entry.is_file() and entry.name not in IGNORED_DIRS]
    )[:50]
    for file_path in iter_repo_files(repo_path, max_files=max(100, max_files)):
        rel_path = file_path.relative_to(repo_path)
        file_count += 1
        ext = file_path.suffix.lower()
        language = LANGUAGE_EXTENSIONS.get(ext)
        if language:
            language_counts[language] += 1
        lower_name = file_path.name.lower()
        if lower_name in BUILD_SYSTEM_HINTS:
            build_files.add(str(rel_path))
            build_systems.add(BUILD_SYSTEM_HINTS[lower_name])
        if lower_name in TEST_FILE_HINTS:
            test_paths.add(str(rel_path))
            test_frameworks.add(TEST_FILE_HINTS[lower_name])
        parents = rel_path.parts
        if parents and parents[0].lower() in {"tests", "test", "__tests__", "spec", "specs"}:
            test_paths.add(str(rel_path))
        if len(parents) >= 2 and parents[0].lower() == "src" and parents[1].lower() == "test":
            test_frameworks.add("junit")
    return {
        "language_counts": dict(language_counts),
        "build_files": sorted(build_files),
        "test_paths": sorted(test_paths),
        "build_systems": sorted(build_systems),
        "test_frameworks": sorted(test_frameworks),
        "file_count": file_count,
        "top_level_files": top_level_files,
    }


def make_snapshot(record: dict[str, object], repo_root: Path, max_files: int) -> RepoSnapshot | None:
    status = record.get("status")
    if status not in {"cloned", "updated"}:
        return None
    local_path_value = record.get("local_path")
    repo_key = record.get("repo_key")
    if not repo_key:
        return None
    local_path = Path(local_path_value) if local_path_value else repo_root / repo_key
    if not local_path.exists():
        return None
    repo_url = str(record.get("repo_url") or "")
    contents = detect_repo_contents(local_path, max_files=max_files)
    language_counts = contents["language_counts"]
    languages = sorted(language_counts, key=language_counts.get, reverse=True)
    resolved_commit = record.get("resolved_commit")
    default_branch = record.get("default_branch")
    return RepoSnapshot(
        repo_key=repo_key,
        repo_url=repo_url,
        local_path=local_path,
        resolved_commit=str(resolved_commit) if resolved_commit else None,
        default_branch=str(default_branch) if default_branch else None,
        languages=languages,
        language_counts=language_counts,
        build_systems=contents["build_systems"],
        test_frameworks=contents["test_frameworks"],
        detected_build_files=contents["build_files"],
        detected_test_paths=contents["test_paths"],
        file_count=contents["file_count"],
        has_tests=bool(contents["test_paths"]),
        has_build_files=bool(contents["build_files"]),
        top_level_files=contents["top_level_files"],
        metadata={
            "selection_rank": record.get("selection_rank"),
            "language_hint": record.get("language"),
            "source_type": record.get("source_type"),
        },
    )


def build_snapshots(
    manifest_records: Sequence[dict[str, object]],
    repo_root: Path,
    max_files: int,
) -> list[RepoSnapshot]:
    snapshots: list[RepoSnapshot] = []
    for record in manifest_records:
        snapshot = make_snapshot(record, repo_root, max_files)
        if snapshot:
            snapshots.append(snapshot)
    return snapshots


def build_snapshot_summary(snapshots: Sequence[RepoSnapshot]) -> dict[str, object]:
    dominant_languages = Counter(snapshot.languages[0] if snapshot.languages else "unknown" for snapshot in snapshots)
    build_counts = Counter(system for snapshot in snapshots for system in snapshot.build_systems)
    test_counts = Counter(framework for snapshot in snapshots for framework in snapshot.test_frameworks)
    return {
        "generated_at": now_utc_iso(),
        "snapshots": len(snapshots),
        "dominant_languages": dict(dominant_languages),
        "build_systems": dict(build_counts),
        "test_frameworks": dict(test_counts),
        "with_tests": sum(1 for snapshot in snapshots if snapshot.has_tests),
        "with_build_files": sum(1 for snapshot in snapshots if snapshot.has_build_files),
    }


def write_snapshot_outputs(
    snapshots: Sequence[RepoSnapshot],
    output_path: Path,
    summary_path: Path,
) -> None:
    write_jsonl(output_path, (snapshot.as_dict() for snapshot in snapshots))
    write_json(summary_path, build_snapshot_summary(snapshots))

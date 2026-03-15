"""Snapshot detection helpers for fetched Topcoder repositories."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".cxx": "C++",
    ".cc": "C++",
    ".c": "C",
    ".rs": "Rust",
    ".swift": "Swift",
}

BUILD_FILE_MAP = {
    "package.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "requirements.txt": "pip",
    "setup.py": "setuptools",
    "pyproject.toml": "pyproject",
    "Pipfile": "pipenv",
    "poetry.lock": "poetry",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "settings.gradle": "gradle",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
}

TEST_HINTS = {
    "pytest.ini": "pytest",
    "tox.ini": "pytest",
    "jest.config.js": "jest",
    "jest.config.cjs": "jest",
    "jest.config.ts": "jest",
    "karma.conf.js": "karma",
    "mocha.opts": "mocha",
    "cypress.config.js": "cypress",
    "cypress.config.ts": "cypress",
    "vitest.config.ts": "vitest",
    "vitest.config.js": "vitest",
    "package.json": "node_tests",
}

PACKAGE_JSON_TEST_KEYS = ("jest", "mocha", "cypress", "vitest", "ava")


@dataclass(slots=True)
class RepoSnapshot:
    snapshot_id: str
    repo_url: str
    source_origin: str
    source_url: str
    local_path: str
    normalized_repo_key: str
    resolved_commit: Optional[str]
    branch: Optional[str]
    archive_hash: Optional[str]
    challenge_ids: List[str]
    top_level_files: List[str]
    detected_languages: List[str]
    detected_build_systems: List[str]
    detected_package_managers: List[str]
    detected_test_frameworks: List[str]
    likely_runnable: bool
    likely_js_repo: bool
    likely_python_repo: bool
    likely_java_repo: bool
    workspace_prep_status: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "repo_url": self.repo_url,
            "source_origin": self.source_origin,
            "source_url": self.source_url,
            "local_path": self.local_path,
            "normalized_repo_key": self.normalized_repo_key,
            "resolved_commit": self.resolved_commit,
            "branch": self.branch,
            "archive_hash": self.archive_hash,
            "challenge_ids": self.challenge_ids,
            "top_level_files": self.top_level_files,
            "detected_languages": self.detected_languages,
            "detected_build_systems": self.detected_build_systems,
            "detected_package_managers": self.detected_package_managers,
            "detected_test_frameworks": self.detected_test_frameworks,
            "likely_runnable": self.likely_runnable,
            "likely_js_repo": self.likely_js_repo,
            "likely_python_repo": self.likely_python_repo,
            "likely_java_repo": self.likely_java_repo,
            "workspace_prep_status": self.workspace_prep_status,
        }


def _iter_files(repo_path: Path, max_files: int = 4000) -> Iterator[Path]:
    count = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d != ".git"]
        for file_name in files:
            yield Path(root) / file_name
            count += 1
            if count >= max_files:
                return


def detect_languages(repo_path: Path) -> Set[str]:
    languages: Set[str] = set()
    for file_path in _iter_files(repo_path):
        language = LANGUAGE_EXTENSIONS.get(file_path.suffix.lower())
        if language:
            languages.add(language)
    return languages


def detect_build_metadata(repo_path: Path) -> Tuple[Set[str], Set[str]]:
    build_systems: Set[str] = set()
    package_managers: Set[str] = set()
    for name, label in BUILD_FILE_MAP.items():
        candidate = repo_path / name
        if candidate.exists():
            build_systems.add(label)
            if label in ("npm", "yarn", "pnpm"):
                package_managers.add(label)
            if label in ("pip", "setuptools", "pyproject", "pipenv", "poetry"):
                package_managers.add(label)
            if label in ("maven", "gradle"):
                package_managers.add(label)
    return build_systems, package_managers


def _parse_package_json(repo_path: Path) -> Dict[str, object]:
    package_file = repo_path / "package.json"
    if not package_file.exists():
        return {}
    try:
        with package_file.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def detect_test_frameworks(repo_path: Path) -> Set[str]:
    frameworks: Set[str] = set()
    for file_name, label in TEST_HINTS.items():
        candidate = repo_path / file_name
        if candidate.exists():
            if label == "node_tests":
                package_data = _parse_package_json(repo_path)
                scripts = package_data.get("scripts") if isinstance(package_data, dict) else None
                if isinstance(scripts, dict):
                    script_values = " ".join(str(value) for value in scripts.values())
                    for key in PACKAGE_JSON_TEST_KEYS:
                        if key in script_values:
                            frameworks.add(key)
            else:
                frameworks.add(label)
    tests_dir = repo_path / "tests"
    if tests_dir.exists():
        frameworks.add("tests_dir")
    return frameworks


def top_level_files(repo_path: Path, limit: int = 80) -> List[str]:
    names: List[str] = []
    for child in sorted(repo_path.iterdir()):
        if child.name == ".git":
            continue
        names.append(child.name)
        if len(names) >= limit:
            break
    return names


def build_snapshot(
    repo_url: str,
    local_path: Path,
    normalized_repo_key: str,
    challenge_ids: List[str],
    resolved_commit: Optional[str],
    branch: Optional[str],
    source_origin: str,
    source_url: str,
    archive_hash: Optional[str],
) -> RepoSnapshot:
    languages = sorted(detect_languages(local_path))
    build_systems, package_managers = detect_build_metadata(local_path)
    frameworks = sorted(detect_test_frameworks(local_path))
    build_list = sorted(build_systems)
    pkg_list = sorted(package_managers)
    runnable = bool(build_list or pkg_list or frameworks)
    snapshot_token = resolved_commit or archive_hash or "unknown"
    return RepoSnapshot(
        snapshot_id=f"{normalized_repo_key}@{snapshot_token}",
        repo_url=repo_url,
        source_origin=source_origin,
        source_url=source_url,
        local_path=str(local_path),
        normalized_repo_key=normalized_repo_key,
        resolved_commit=resolved_commit,
        branch=branch,
        archive_hash=archive_hash,
        challenge_ids=challenge_ids,
        top_level_files=top_level_files(local_path),
        detected_languages=languages,
        detected_build_systems=build_list,
        detected_package_managers=pkg_list,
        detected_test_frameworks=frameworks,
        likely_runnable=runnable,
        likely_js_repo=any(lang in {"JavaScript", "TypeScript"} for lang in languages),
        likely_python_repo="Python" in languages,
        likely_java_repo="Java" in languages,
        workspace_prep_status="pending",
    )

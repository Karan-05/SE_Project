"""Heuristically route heterogeneous Topcoder tasks to specialized solvers."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


class TaskType(str, enum.Enum):
    """Canonical task families handled by the universal solver."""

    ALGO_CODING = "algo_coding"
    REPO_PATCH = "repo_patch"
    API_BACKEND = "api_backend"
    ARCHITECTURE_DOC = "architecture_doc"
    DATA_ETL = "data_etl"
    NON_ACTIONABLE = "non_actionable"


@dataclass
class RoutingDecision:
    """Result emitted by the task router."""

    task_type: TaskType
    rationale: str
    heuristics: List[str]


CODING_KEYWORDS = [
    "input:",
    "output:",
    "stdin",
    "stdout",
    "sample",
    "example",
    "constraints",
    "function",
    "method",
    "return the",
]
REPO_KEYWORDS = [
    "app",
    "application",
    "react",
    "angular",
    "nextjs",
    "node",
    "django",
    "flask",
    "java",
    "spring",
    "android",
    "ios",
    "markdown",
    "ui",
    "ux",
    "frontend",
    "frontend",
    "component",
    "backend",
    "bug",
    "fix",
    "issue",
    "bugfix",
    "pull request",
    "pr ",
    "merge",
    "branch",
    "git ",
    "github",
    "gitlab",
    "repository",
]
API_KEYWORDS = [
    "api",
    "endpoint",
    "service",
    "microservice",
    "graphql",
    "rest",
    "swagger",
    "openapi",
    "soap",
    "http",
    "webhook",
    "oauth",
    "jwt",
    "request/response",
    "json payload",
    "controller",
]
ARCHITECTURE_KEYWORDS = [
    "design",
    "architecture",
    "proposal",
    "plan",
    "document",
    "specification",
    "roadmap",
    "system",
    "system design",
    "strategy",
    "rfc",
    "blueprint",
]
DATA_ETL_KEYWORDS = [
    "etl",
    "extract",
    "transform",
    "load",
    "data pipeline",
    "analytics",
    "warehouse",
    "lake",
    "lakehouse",
    "schema",
    "sql",
    "bigquery",
    "redshift",
    "snowflake",
    "ingest",
    "ingestion",
    "airflow",
    "dbt",
    "spark",
    "cdc",
    "kafka",
    "delta lake",
    "export",
    "csv",
    "parquet",
]
HIRING_KEYWORDS = [
    "hiring",
    "opportunity",
    "role",
    "position",
    "seeking",
    "talent",
    "apply now",
    "specialist",
    "engineer role",
    "job",
]
TEST_CHALLENGE_KEYWORDS = [
    "test challenge",
    "skill test",
    "practice challenge",
    "screening task",
    "assessment",
]
ACTIONABLE_ANCHORS = [
    "http",
    "www",
    "github",
    "gitlab",
    "repo",
    "repository",
    "api",
    "endpoint",
    "swagger",
    "openapi",
    "database",
    "dataset",
    "sql",
    "schema",
    "pipeline",
    "etl",
    "spark",
    "airflow",
    "dbt",
    "architecture",
    "design",
    "feature",
    "bug",
]


def _text_blobs(task: Dict[str, Any]) -> Tuple[str, str]:
    statement = str(task.get("problem_statement") or task.get("statement") or "").strip()
    title = str(task.get("title") or "").strip()
    tags = task.get("tags") or task.get("challengeTags") or []
    if isinstance(tags, str):
        tags_blob = tags
    else:
        tags_blob = " ".join(str(tag) for tag in tags if tag)
    blob = f"{title}\n{tags_blob}"
    return blob.lower(), statement.lower()


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _has_function_signature(statement: str) -> bool:
    signature_markers = (
        "def ",
        "class ",
        "public ",
        "private ",
        "function ",
        "::",
        "->",
    )
    if any(marker in statement for marker in signature_markers):
        return True
    return False


def _has_io_examples(statement: str) -> bool:
    if "input:" in statement and "output:" in statement:
        return True
    if "stdin" in statement or "stdout" in statement:
        return True
    return False


def _normalize_tests(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = task.get("metadata") or {}
    tests = metadata.get("tests") or []
    if isinstance(tests, list):
        return tests
    return []


def _count_examples(task: Dict[str, Any]) -> int:
    examples = task.get("examples") or []
    if isinstance(examples, list):
        return len(examples)
    return 0


def _looks_like_hiring(title_blob: str, statement: str) -> bool:
    combined = f"{title_blob} {statement}"
    return any(keyword in combined for keyword in HIRING_KEYWORDS)


def _looks_like_test_challenge(title_blob: str, statement: str) -> bool:
    combined = f"{title_blob} {statement}"
    short_spec = len(statement.split()) < 80
    return short_spec and any(keyword in combined for keyword in TEST_CHALLENGE_KEYWORDS)


def _has_actionable_anchor(text: str) -> bool:
    return any(anchor in text for anchor in ACTIONABLE_ANCHORS)


def _parse_force_type(force_task_type: Optional[str]) -> Optional[TaskType]:
    if not force_task_type:
        return None
    normalized = force_task_type.strip().replace("-", "_").upper()
    for task_type in TaskType:
        if task_type.name == normalized or task_type.value.upper() == normalized:
            return task_type
    return None


def route_task(task: Dict[str, Any], *, force_task_type: Optional[str] = None) -> RoutingDecision:
    """Classify a dataset entry so we can dispatch to the right solver."""

    forced = _parse_force_type(force_task_type)
    title, statement = _text_blobs(task)
    heuristics: List[str] = []
    if forced:
        heuristics.append(f"forced:{forced.value}")
        return RoutingDecision(task_type=forced, rationale="Forced via CLI override", heuristics=heuristics)

    combined = f"{title} {statement}"
    if _looks_like_hiring(title, statement):
        heuristics.append("hiring_signal")
        return RoutingDecision(TaskType.NON_ACTIONABLE, "Detected hiring/recruiting language", heuristics)
    if _looks_like_test_challenge(title, statement):
        heuristics.append("test_challenge_stub")
        return RoutingDecision(TaskType.NON_ACTIONABLE, "Detected short screening/test challenge without requirements", heuristics)
    tests = _normalize_tests(task)
    has_examples = _count_examples(task) >= 1
    has_signature = _has_function_signature(statement)
    has_io = _has_io_examples(statement)
    has_actionable_anchors = _has_actionable_anchor(combined)
    if tests:
        heuristics.append("metadata_tests")
        return RoutingDecision(TaskType.ALGO_CODING, "Executable tests were provided", heuristics)
    if has_examples:
        heuristics.append("examples_present")
    if has_signature:
        heuristics.append("function_signature")
    if has_io:
        heuristics.append("io_markers")
    if has_examples and (has_signature or has_io):
        return RoutingDecision(TaskType.ALGO_CODING, "Examples include callable IO specifications", heuristics)
    if has_io and has_signature:
        return RoutingDecision(TaskType.ALGO_CODING, "Clear IO markers with explicit signature", heuristics)

    if not statement or len(statement) < 40:
        heuristics.append("missing_statement")
        return RoutingDecision(TaskType.NON_ACTIONABLE, "Insufficient details to act on", heuristics)

    if _has_any(combined, DATA_ETL_KEYWORDS):
        heuristics.append("data_etl_keywords")
        return RoutingDecision(TaskType.DATA_ETL, "Mentions ETL/pipeline terminology", heuristics)

    if _has_any(combined, API_KEYWORDS):
        heuristics.append("api_keywords")
        return RoutingDecision(TaskType.API_BACKEND, "Describes backend/API endpoints", heuristics)

    if _has_any(combined, REPO_KEYWORDS):
        heuristics.append("repo_keywords")
        return RoutingDecision(TaskType.REPO_PATCH, "Looks like repository/app maintenance task", heuristics)

    architecture_signal = _has_any(combined, ARCHITECTURE_KEYWORDS) and len(statement) >= 80
    if architecture_signal:
        heuristics.append("architecture_keywords")
        return RoutingDecision(TaskType.ARCHITECTURE_DOC, "High level design/spec request detected", heuristics)

    if not has_actionable_anchors and len(statement) < 200 and not (has_io or has_signature):
        heuristics.append("no_actionable_anchors")
        return RoutingDecision(TaskType.NON_ACTIONABLE, "Missing repo/API/data references to act upon", heuristics)

    if has_io and _has_any(statement, CODING_KEYWORDS):
        heuristics.append("coding_keywords")
        return RoutingDecision(TaskType.ALGO_CODING, "Contains IO markers with coding instructions", heuristics)

    heuristics.append("default")
    return RoutingDecision(TaskType.ARCHITECTURE_DOC, "Defaulted to design/spec mode", heuristics)


__all__ = ["TaskType", "RoutingDecision", "route_task"]

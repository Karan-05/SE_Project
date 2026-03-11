"""Helpers for task-level contracts and semantic coverage."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence


@dataclass
class ContractItem:
    """Normalized contract entry derived from task metadata."""

    id: str
    description: str
    category: str
    tests: Sequence[str] = field(default_factory=tuple)
    keywords: Sequence[str] = field(default_factory=tuple)

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "ContractItem":
        tests = tuple(str(item) for item in payload.get("tests", []) or [])
        keywords = tuple(str(item).lower() for item in payload.get("keywords", []) or [])
        return ContractItem(
            id=str(payload.get("id") or payload.get("name") or payload.get("description") or "contract"),
            description=str(payload.get("description") or ""),
            category=str(payload.get("category") or "general"),
            tests=tests,
            keywords=keywords,
        )


@dataclass
class ContractCoverageResult:
    """Outcome of mapping failing tests onto contract items."""

    total: int
    satisfied_ids: List[str]
    unsatisfied_ids: List[str]
    categories: Dict[str, int]
    coverage: float
    failing_cases: List[str]


FAIL_LINE_PATTERN = re.compile(r"^\s*\d+\)\s+(.*)")
IT_LINE_PATTERN = re.compile(r"^\s{2,}(.+)")


def parse_mocha_failures(log_text: str) -> List[str]:
    """Extract describe::it names from mocha stderr."""

    cases: List[str] = []
    lines = log_text.splitlines()
    idx = 0
    while idx < len(lines):
        match = FAIL_LINE_PATTERN.match(lines[idx])
        if match:
            describe = match.group(1).strip()
            it_name = ""
            if idx + 1 < len(lines):
                it_match = IT_LINE_PATTERN.match(lines[idx + 1])
                if it_match:
                    it_name = it_match.group(1).strip().rstrip(":")
            if describe:
                label = describe if not it_name else f"{describe}::{it_name}"
                cases.append(label)
        idx += 1
    return cases


def get_contract_items(metadata: Dict[str, object]) -> List[ContractItem]:
    raw_items = metadata.get("contract") or []
    if not isinstance(raw_items, Iterable):
        return []
    items: List[ContractItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        items.append(ContractItem.from_dict(entry))
    return items


def format_contract_summary(items: Sequence[ContractItem]) -> str:
    if not items:
        return "No explicit contract entries; follow task prompt and tests tightly."
    parts = [f"- [{item.category}] {item.description.strip()}" for item in items]
    return "\n".join(parts)


def evaluate_contract_coverage(
    metadata: Dict[str, object],
    test_records: Sequence[Dict[str, object]],
) -> ContractCoverageResult:
    items = get_contract_items(metadata)
    if not items:
        return ContractCoverageResult(0, [], [], {}, 0.0, [])
    failing_logs = [str(record.get("stderr") or "") for record in test_records if record.get("status") != "pass"]
    failing_cases: List[str] = []
    for log in failing_logs:
        if not log:
            continue
        failing_cases.extend(parse_mocha_failures(log))
    failing_case_set = {case.strip() for case in failing_cases if case.strip()}
    unsatisfied: List[str] = []
    satisfied: List[str] = []
    categories: Dict[str, int] = {}
    lower_logs = [log.lower() for log in failing_logs]
    for item in items:
        item_unsatisfied = False
        if item.tests:
            for label in item.tests:
                if label and label in failing_case_set:
                    item_unsatisfied = True
                    break
        if not item_unsatisfied and item.keywords and lower_logs:
            for keyword in item.keywords:
                if not keyword:
                    continue
                if any(keyword in log for log in lower_logs):
                    item_unsatisfied = True
                    break
        if item_unsatisfied:
            unsatisfied.append(item.id)
            categories[item.category] = categories.get(item.category, 0) + 1
        else:
            satisfied.append(item.id)
    coverage = len(satisfied) / len(items) if items else 0.0
    return ContractCoverageResult(
        total=len(items),
        satisfied_ids=satisfied,
        unsatisfied_ids=unsatisfied,
        categories=categories,
        coverage=coverage,
        failing_cases=failing_cases,
    )


def render_unsatisfied_details(metadata: Dict[str, object], unsatisfied_ids: Sequence[str]) -> List[str]:
    """Return a list of textual descriptions for the unsatisfied ids."""

    items = {item.id: item for item in get_contract_items(metadata)}
    details: List[str] = []
    for cid in unsatisfied_ids:
        entry = items.get(cid)
        if not entry:
            continue
        details.append(f"{cid}: {entry.description}")
    return details


__all__ = [
    "ContractItem",
    "ContractCoverageResult",
    "evaluate_contract_coverage",
    "format_contract_summary",
    "get_contract_items",
    "parse_mocha_failures",
    "render_unsatisfied_details",
]

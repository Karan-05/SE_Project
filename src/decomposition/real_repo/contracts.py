"""Helpers for task-level contracts and semantic coverage."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass
class ContractItem:
    """Normalized contract entry derived from task metadata."""

    id: str
    label: str
    description: str
    category: str
    expected_behavior: str = ""
    priority: str = ""
    source: str = ""
    notes: str = ""
    tests: Sequence[str] = field(default_factory=tuple)
    keywords: Sequence[str] = field(default_factory=tuple)

    @staticmethod
    def from_dict(payload: Dict[str, object], default_id: Optional[str] = None) -> "ContractItem":
        tests = tuple(str(item) for item in payload.get("tests", []) or [])
        keywords = tuple(str(item).lower() for item in payload.get("keywords", []) or [])
        cid = str(payload.get("id") or payload.get("name") or payload.get("clause_id") or "").strip()
        if not cid:
            cid = str(default_id or "clause_0")
        label = str(payload.get("label") or payload.get("name") or cid).strip() or cid
        expected = str(
            payload.get("expected_behavior")
            or payload.get("expected")
            or payload.get("behavior")
            or payload.get("description")
            or ""
        )
        return ContractItem(
            id=cid,
            label=label,
            description=str(payload.get("description") or ""),
            category=str(payload.get("category") or "general"),
            expected_behavior=expected,
            priority=str(payload.get("priority") or payload.get("tier") or ""),
            source=str(payload.get("source") or payload.get("origin") or ""),
            notes=str(payload.get("notes") or ""),
            tests=tests,
            keywords=keywords,
        )

    def to_trace_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "label": self.label or self.id,
            "description": self.description,
            "category": self.category,
            "expected_behavior": self.expected_behavior or self.description,
            "test_refs": list(self.tests),
            "priority": self.priority,
            "source": self.source,
            "notes": self.notes,
            "keywords": list(self.keywords),
        }


@dataclass
class ContractCoverageResult:
    """Outcome of mapping failing tests onto contract items."""

    total: int
    satisfied_ids: List[str]
    unsatisfied_ids: List[str]
    categories: Dict[str, int]
    coverage: float
    failing_cases: List[str]
    failure_label_map: Dict[str, List[str]] = field(default_factory=dict)


FAIL_LINE_PATTERN = re.compile(r"^\s*\d+\)\s+(.*)")
IT_LINE_PATTERN = re.compile(r"^\s{2,}(.+)")
PLACEHOLDER_TOKENS = {"tbd", "todo", "none", "n/a", "underspecified", "placeholder", "undocumented"}


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
    seen_ids: set[str] = set()
    for idx, entry in enumerate(raw_items):
        if not isinstance(entry, dict):
            continue
        item = ContractItem.from_dict(entry, default_id=f"clause_{idx}")
        base_id = item.id
        suffix = 1
        while item.id in seen_ids:
            item.id = f"{base_id}_{suffix}"
            suffix += 1
        seen_ids.add(item.id)
        items.append(item)
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
        return ContractCoverageResult(0, [], [], {}, 0.0, [], {})

    def _read_log(record: Dict[str, object]) -> str:
        content: List[str] = []
        stderr = record.get("stderr")
        stdout = record.get("stdout")
        log_path = record.get("log_path")
        if stderr:
            content.append(str(stderr))
        if stdout:
            content.append(str(stdout))
        if log_path:
            try:
                data = Path(str(log_path)).read_text(encoding="utf-8")
            except OSError:
                data = ""
            if data:
                content.append(data)
        return "\n".join(content)

    failing_logs = [
        _read_log(record) for record in test_records if record.get("status") not in {"pass", "passed"}
    ]
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
    label_map: Dict[str, List[str]] = {}
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
            labels_to_track = []
            if item.tests:
                labels_to_track.extend(
                    label for label in item.tests if label and label in failing_case_set
                )
            if not labels_to_track and item.keywords:
                for keyword in item.keywords:
                    if not keyword:
                        continue
                    for case in failing_case_set:
                        if keyword in case.lower():
                            labels_to_track.append(case)
                            break
                    if labels_to_track:
                        break
            if not labels_to_track and item.keywords:
                labels_to_track.extend(f"keyword:{kw}" for kw in item.keywords if kw)
            for label in labels_to_track:
                label_map.setdefault(label, [])
                if item.id not in label_map[label]:
                    label_map[label].append(item.id)
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
        failure_label_map=label_map,
    )


def contract_items_to_dicts(items: Sequence[ContractItem]) -> List[Dict[str, object]]:
    return [item.to_trace_dict() for item in items]


def classify_contract_quality(items: Sequence[object]) -> str:
    if not items:
        return "missing"
    descriptions = []
    for item in items:
        if isinstance(item, ContractItem):
            value = item.description
        elif isinstance(item, dict):
            value = str(item.get("description") or "")
        else:
            value = str(getattr(item, "description", ""))
        value = value.strip().lower()
        if value:
            descriptions.append(value)
    if descriptions and all(any(token in desc for token in PLACEHOLDER_TOKENS) for desc in descriptions):
        return "weak"
    return "strong"


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
    "contract_items_to_dicts",
    "classify_contract_quality",
    "parse_mocha_failures",
    "render_unsatisfied_details",
]

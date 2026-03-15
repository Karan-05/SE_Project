"""Semantic witness extraction from repo-backed test output."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from src.decomposition.real_repo.contracts import ContractItem

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
FAIL_HEADER_PATTERN = re.compile(r"^\s*\d+\)\s+(?P<block>.+)")
IT_BLOCK_PATTERN = re.compile(r"^\s{2,}(?P<it>.+)")
INLINE_EXPECT_PATTERN = re.compile(
    r"expected\s+(?P<actual>.+?)\s+to\s+(?:deep\s+)?(?:strictly\s+)?(?:equal|eql|be|contain)\s+(?P<expected>.+)",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return ANSI_PATTERN.sub("", text or "").strip()


def _read_log(log_path: str) -> str:
    if not log_path:
        return ""
    try:
        data = Path(log_path).read_text(encoding="utf-8")
    except OSError:
        return ""
    return data


def _categorize(message: str, record_status: str) -> str:
    lower = (message or "").lower()
    status_lower = (record_status or "").lower()
    if "assertionerror" in lower or "expected" in lower:
        return "assertion"
    if "timeout" in lower or status_lower == "timeout":
        return "timeout"
    if "typeerror" in lower:
        return "type_error"
    if "referenceerror" in lower:
        return "reference_error"
    if "syntaxerror" in lower:
        return "syntax"
    if "enoent" in lower or "not found" in lower:
        return "missing_resource"
    if "build_failed" in status_lower or "build" in lower:
        return "build"
    return "general"


def _split_failure_blocks(log_text: str) -> List[Dict[str, object]]:
    lines = log_text.splitlines()
    idx = 0
    blocks: List[Dict[str, object]] = []
    total = len(lines)
    while idx < total:
        header = FAIL_HEADER_PATTERN.match(lines[idx])
        if not header:
            idx += 1
            continue
        describe = _clean(header.group("block"))
        idx += 1
        it_name = ""
        if idx < total:
            it_match = IT_BLOCK_PATTERN.match(lines[idx])
            if it_match:
                it_name = _clean(it_match.group("it")).rstrip(":")
                idx += 1
        snippet: List[str] = []
        while idx < total and not FAIL_HEADER_PATTERN.match(lines[idx]):
            snippet.append(lines[idx])
            idx += 1
        label = describe if not it_name else f"{describe}::{it_name}"
        blocks.append({"label": label, "snippet": snippet})
    return blocks


def _extract_message(snippet: Sequence[str]) -> str:
    for line in snippet:
        cleaned = _clean(line)
        if not cleaned:
            continue
        if "AssertionError" in cleaned or "Error" in cleaned or "Exception" in cleaned:
            return cleaned
    for line in snippet:
        cleaned = _clean(line)
        if cleaned:
            return cleaned
    return ""


def _extract_expected_actual(snippet: Sequence[str]) -> Tuple[str, str]:
    expected = ""
    actual = ""
    for idx, line in enumerate(snippet):
        cleaned = _clean(line)
        if cleaned.lower().startswith("+ expected - actual"):
            if idx + 1 < len(snippet):
                actual = _clean(snippet[idx + 1]).lstrip("-").strip()
            if idx + 2 < len(snippet):
                expected = _clean(snippet[idx + 2]).lstrip("+").strip()
            if expected or actual:
                return expected, actual
        inline = INLINE_EXPECT_PATTERN.search(cleaned)
        if inline:
            actual_candidate = inline.group("actual").strip()
            expected_candidate = inline.group("expected").strip()
            if actual_candidate:
                actual = actual or actual_candidate
            if expected_candidate:
                expected = expected or expected_candidate
    return expected, actual


@dataclass
class SemanticWitness:
    """Structured evidence for a failing semantic clause."""

    test_case: str
    message: str = ""
    expected: str = ""
    actual: str = ""
    location: str = ""
    category: str = "general"
    linked_contract_ids: List[str] = field(default_factory=list)


def extract_mocha_witnesses(test_records: Sequence[Dict[str, object]]) -> List[SemanticWitness]:
    """Extract structured witnesses from mocha-style test output."""

    witnesses: List[SemanticWitness] = []
    for record in test_records:
        status = str(record.get("status") or "").lower()
        if status in {"pass", "passed"}:
            continue
        stderr = record.get("stderr") or ""
        stdout = record.get("stdout") or ""
        log_blob = _read_log(str(record.get("log_path") or "")) if record.get("log_path") else ""
        combined = "\n".join(text for text in [str(stderr), str(stdout), log_blob] if text)
        if not combined.strip():
            combined = str(stderr) or str(stdout) or ""
        blocks = _split_failure_blocks(combined)
        if not blocks:
            message = _clean(stderr or stdout or status or "failure")
            witnesses.append(
                SemanticWitness(
                    test_case=str(record.get("name") or record.get("cmd") or "tests"),
                    message=message,
                    expected="",
                    actual="",
                    location=str(record.get("log_path") or ""),
                    category=_categorize(message, status),
                )
            )
            continue
        for block in blocks:
            snippet = block.get("snippet") or []
            message = _extract_message(snippet)
            expected, actual = _extract_expected_actual(snippet)
            witnesses.append(
                SemanticWitness(
                    test_case=str(block.get("label") or record.get("name") or "tests"),
                    message=message,
                    expected=expected,
                    actual=actual,
                    location=str(record.get("log_path") or ""),
                    category=_categorize(message, status),
                )
            )
    return witnesses


def witness_signature(witness: SemanticWitness) -> str:
    """Generate a deterministic signature for deduplicating witnesses."""

    digest_input = "||".join(
        [
            witness.test_case or "",
            witness.category or "",
            witness.message or "",
            witness.expected or "",
            witness.actual or "",
            ",".join(sorted(witness.linked_contract_ids)),
        ]
    ).encode("utf-8")
    return hashlib.sha1(digest_input).hexdigest()


def link_witnesses_to_contract(
    contract_items: Iterable[ContractItem],
    witnesses: Sequence[SemanticWitness],
) -> Dict[str, List[SemanticWitness]]:
    """Associate witnesses with contract items via test labels and keywords."""

    items = list(contract_items)
    mapping: Dict[str, List[SemanticWitness]] = {item.id: [] for item in items}
    mapping["__unmapped__"] = []
    lowered_tests = {item.id: [str(test).lower() for test in item.tests] for item in items}
    lowered_keywords = {item.id: [str(kw).lower() for kw in item.keywords] for item in items}
    for witness in witnesses:
        witness_text = f"{witness.test_case} {witness.message}".lower()
        linked_ids: List[str] = []
        for item in items:
            tests = lowered_tests.get(item.id, [])
            keywords = lowered_keywords.get(item.id, [])
            test_match = any(test and test in witness.test_case.lower() for test in tests)
            keyword_match = any(keyword and keyword in witness_text for keyword in keywords)
            if test_match or keyword_match:
                mapping[item.id].append(witness)
                linked_ids.append(item.id)
        if linked_ids:
            merged = set(witness.linked_contract_ids)
            merged.update(linked_ids)
            witness.linked_contract_ids = sorted(merged)
        else:
            mapping["__unmapped__"].append(witness)
    return mapping


__all__ = [
    "SemanticWitness",
    "extract_mocha_witnesses",
    "link_witnesses_to_contract",
    "witness_signature",
]

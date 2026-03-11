"""Deterministic rubric verifier for non-coding deliverables."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..solvers.base import sanitize_task_id


@dataclass
class RubricResult:
    score: float
    passes_threshold: bool
    reasons: List[str]
    missing: List[str]
    raw: Dict[str, Any]
    path: Path
    relaxed_due_to_context: bool = False


class RubricVerifier:
    """Deterministically score deliverables using rubric heuristics."""

    def __init__(self, rubric_dir: Path, default_threshold: float = 70.0):
        self.rubric_dir = rubric_dir
        self.default_threshold = default_threshold
        rubric_dir.mkdir(parents=True, exist_ok=True)

    def evaluate(
        self,
        *,
        task: Dict[str, Any],
        deliverable_text: str,
        rubric_name: str,
        required_sections: Optional[Iterable[str]] = None,
        threshold: Optional[float] = None,
        artifacts: Optional[Dict[str, str]] = None,
    ) -> RubricResult:
        sections = [section.strip() for section in (required_sections or []) if section]
        threshold_value = self.default_threshold if threshold is None else threshold
        normalized = deliverable_text or ""
        coverage, missing = self._section_coverage(normalized, sections)
        extra_score, reasons = self._rubric_specific_score(rubric_name, normalized)
        overall_score = round(100 * min(1.0, 0.6 * coverage + 0.4 * extra_score), 1)
        metadata = task.get("metadata") or {}
        repo_unavailable = bool(metadata.get("repo_unavailable"))
        insufficient_context = bool(metadata.get("insufficient_context"))
        relaxed_due_to_context = False
        adjusted_threshold = threshold_value
        if repo_unavailable:
            required_artifacts = {"patch_plan.md", "proposed_patch.diff", "test_plan.md", "risks.md"}
            artifact_map = artifacts or {}
            if all(str(artifact_map.get(name, "")).strip() for name in required_artifacts):
                adjusted_threshold = max(threshold_value * 0.75, threshold_value - 15)
                relaxed_due_to_context = True
        elif insufficient_context:
            adjusted_threshold = max(threshold_value * 0.85, threshold_value - 5)
            relaxed_due_to_context = True
        passes = overall_score >= adjusted_threshold and (relaxed_due_to_context or not missing)
        payload = {
            "score": overall_score,
            "passes_threshold": passes,
            "reasons": reasons,
            "missing": missing,
            "section_coverage": coverage,
            "extra_score": extra_score,
            "relaxed_due_to_context_missing": relaxed_due_to_context,
        }
        safe = sanitize_task_id(task.get("id") or "task")
        path = self.rubric_dir / f"{safe}_{rubric_name}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return RubricResult(
            score=overall_score,
            passes_threshold=passes,
            reasons=reasons,
            missing=missing,
            raw=payload,
            path=path,
            relaxed_due_to_context=relaxed_due_to_context,
        )

    def _section_coverage(self, text: str, sections: List[str]) -> Tuple[float, List[str]]:
        if not sections:
            return 1.0, []
        headings = self._extract_headings(text)
        missing = [section for section in sections if section.lower() not in headings]
        coverage = 1.0 - (len(missing) / len(sections))
        return max(0.0, min(1.0, coverage)), missing

    def _extract_headings(self, text: str) -> List[str]:
        headings = []
        pattern = re.compile(r"^\s{0,3}#{1,6}\s*(.+)$", re.MULTILINE)
        for match in pattern.finditer(text):
            headings.append(match.group(1).strip().lower())
        colon_pattern = re.compile(r"^\s{0,3}([A-Za-z0-9 /&]+?)\s*:\s*$", re.MULTILINE)
        for match in colon_pattern.finditer(text):
            candidate = match.group(1).strip().lower()
            if candidate and candidate not in headings:
                headings.append(candidate)
        return headings

    def _rubric_specific_score(self, rubric_name: str, text: str) -> Tuple[float, List[str]]:
        rubric = rubric_name.lower()
        text_lower = text.lower()
        if rubric in {"architecture_doc", "design_doc"}:
            return self._score_architecture(text_lower)
        if rubric in {"repo_patch", "api_backend"}:
            return self._score_repo_patch(text_lower)
        if rubric == "data_etl":
            return self._score_data_etl(text_lower)
        return self._score_generic(text_lower)

    def _score_architecture(self, text_lower: str) -> Tuple[float, List[str]]:
        constraints = bool(re.search(r"constraint|sla|latency|throughput|budget|limit", text_lower))
        tradeoffs = bool(re.search(r"trade[- ]?off|alternative|option", text_lower))
        diagrams = bool(re.search(r"diagram|sequence|flowchart|mermaid", text_lower))
        risks = bool(re.search(r"risk|fallback|mitigation", text_lower))
        has_components = bool(re.search(r"component|module|service|api", text_lower))
        signals = [constraints, tradeoffs, diagrams, risks, has_components]
        score = sum(1 for flag in signals if flag) / len(signals)
        reasons: List[str] = []
        if constraints:
            reasons.append("Includes constraints/SLAs")
        if tradeoffs:
            reasons.append("Trade-offs discussed")
        if diagrams:
            reasons.append("Diagram reference present")
        if risks:
            reasons.append("Risks and mitigations described")
        if has_components:
            reasons.append("Component mapping provided")
        if not reasons:
            reasons = ["Missing advanced architecture signals"]
        return score, reasons

    def _score_repo_patch(self, text_lower: str) -> Tuple[float, List[str]]:
        plan = bool(re.search(r"plan|approach|steps", text_lower))
        diff = bool(re.search(r"diff --git|```diff|@@", text_lower))
        risks = "risk" in text_lower
        validation = bool(re.search(r"test|qa|validation|checks", text_lower))
        artifacts = bool(re.search(r"patch|apply|command", text_lower))
        components = [plan, diff, risks, validation, artifacts]
        score = sum(components) / len(components)
        reasons = []
        if plan:
            reasons.append("Plan present")
        if diff:
            reasons.append("Diff snippet detected")
        if risks:
            reasons.append("Risks documented")
        if validation:
            reasons.append("Validation/tests listed")
        if artifacts:
            reasons.append("Patch/application guidance provided")
        if not reasons:
            reasons = ["No repo plan content detected"]
        return score, reasons

    def _score_data_etl(self, text_lower: str) -> Tuple[float, List[str]]:
        schema = bool(re.search(r"schema|table|column", text_lower))
        pipeline = bool(re.search(r"stage|transform|ingest|step", text_lower))
        invariants = bool(re.search(r"quality|invariant|validation", text_lower))
        queries = bool(re.search(r"select |query|sql|cte", text_lower))
        samples = bool(re.search(r"sample|example|preview|dataset", text_lower))
        components = [schema, pipeline, invariants, queries, samples]
        score = sum(components) / len(components)
        reasons = []
        if schema:
            reasons.append("Schema defined")
        if pipeline:
            reasons.append("Pipeline steps listed")
        if invariants:
            reasons.append("Data quality or invariants addressed")
        if queries:
            reasons.append("Validation queries present")
        if samples:
            reasons.append("Sample outputs described")
        if not reasons:
            reasons = ["Missing ETL blueprint details"]
        return score, reasons

    def _score_generic(self, text_lower: str) -> Tuple[float, List[str]]:
        bullets = text_lower.count("- ")
        code_blocks = text_lower.count("```")
        detail = min(1.0, (bullets + code_blocks) / 10.0)
        reasons = [f"Generic detail score {detail:.2f}"]
        return detail, reasons

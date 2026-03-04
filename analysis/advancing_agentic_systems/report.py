"""CLI entry point for generating agentic analysis across Topcoder challenges."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .baselines import get_baseline
from .metrics import evaluate_plan_against_baseline
from .plan_generation import build_agentic_plan
from .paper_alignment import write_alignment_brief


def _iter_challenge_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("page*.json")):
        if path.is_file():
            yield path


def _load_challenges(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            return []
    return []


def _select_baseline_key(challenge: Dict[str, Any], plan) -> str:
    track = (challenge.get("trackType") or challenge.get("track") or "").lower()
    ctype = (challenge.get("type") or "").lower()
    technologies = [t.strip().lower() for t in (challenge.get("technologies") or "").split(",") if t.strip()]
    text_blob = " ".join([
        challenge.get("name") or "",
        challenge.get("description") or "",
        " ".join(technologies),
    ]).lower()

    ai_keywords = (
        " ai ",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "computer vision",
        "autonomous",
        "multi-agent",
        "agentic",
        "rag",
        "llm",
        "generative",
        "reinforcement learning",
    )
    is_ai_theme = any(keyword in text_blob for keyword in ai_keywords)

    if "design" in track or "design" in ctype:
        return "design_parallel"
    if "qa" in track or "test" in ctype:
        return "qa_sequential"
    if any(keyword in track for keyword in ("data", "analytics", "ds")) or any(keyword in technologies for keyword in ("ml", "ai", "data")) or is_ai_theme:
        return "data_science_hybrid"
    if plan.scenario_type == "sequential":
        return "dev_sequential_coarse"
    return "dev_parallel_fine"


def _plan_to_dict(plan) -> Dict[str, Any]:
    return {
        "scenarioType": plan.scenario_type,
        "granularity": plan.granularity,
        "nodes": [
            {
                "id": node.node_id,
                "label": node.label,
                "tools": list(node.tools),
                "parallelGroup": node.parallel_group,
            }
            for node in plan.nodes.values()
        ],
        "edges": [{"source": edge.source, "target": edge.target} for edge in plan.edges],
        "notes": list(plan.notes),
    }


def _evaluation_to_dict(metrics) -> Dict[str, Any]:
    return {
        "baselineId": metrics.baseline_id,
        "nodePrecision": round(metrics.node_precision, 3),
        "nodeRecall": round(metrics.node_recall, 3),
        "nodeF1": round(metrics.node_f1, 3),
        "edgePrecision": round(metrics.edge_precision, 3),
        "edgeRecall": round(metrics.edge_recall, 3),
        "edgeF1": round(metrics.edge_f1, 3),
        "toolPrecision": round(metrics.tool_precision, 3),
        "toolRecall": round(metrics.tool_recall, 3),
        "toolF1": round(metrics.tool_f1, 3),
        "nodeLabelSimilarity": round(metrics.node_label_similarity, 3),
        "structuralSimilarityIndex": round(metrics.structural_similarity_index, 3),
        "pathLengthSimilarity": round(metrics.path_length_similarity, 3),
        "complexityScore": metrics.complexity_score,
    }


def generate_reports(
    challenge_root: Path,
    output_root: Path,
    prefer_fine_grained: bool,
    include_incomplete: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    annotations_by_id: Dict[str, Dict[str, Any]] = {}
    metrics_by_id: Dict[str, Dict[str, Any]] = {}

    for path in _iter_challenge_files(challenge_root):
        challenges = _load_challenges(path)
        if not challenges and not include_incomplete:
            continue

        for challenge in challenges:
            challenge_id = challenge.get("challengeId") or challenge.get("id")
            if not challenge_id and not include_incomplete:
                continue

            plan = build_agentic_plan(challenge, prefer_fine_grained=prefer_fine_grained)
            baseline_key = _select_baseline_key(challenge, plan)
            baseline = get_baseline(baseline_key)
            evaluation = evaluate_plan_against_baseline(plan, baseline.plan, baseline.baseline_id)

            annotation_entry = {
                "challengeId": challenge.get("challengeId"),
                "legacyId": challenge.get("legacyId"),
                "name": challenge.get("name"),
                "trackType": challenge.get("trackType"),
                "type": challenge.get("type"),
                "status": challenge.get("status"),
                "baseline": baseline.baseline_id,
                "plan": _plan_to_dict(plan),
                "metrics": _evaluation_to_dict(evaluation),
            }
            metrics_row = {
                "challengeId": challenge.get("challengeId"),
                "name": challenge.get("name"),
                "trackType": challenge.get("trackType"),
                "status": challenge.get("status"),
                "baselineId": baseline.baseline_id,
                "scenarioType": evaluation.scenario_type,
                "granularity": evaluation.granularity,
                "nodePrecision": evaluation.node_precision,
                "nodeRecall": evaluation.node_recall,
                "nodeF1": evaluation.node_f1,
                "edgePrecision": evaluation.edge_precision,
                "edgeRecall": evaluation.edge_recall,
                "edgeF1": evaluation.edge_f1,
                "toolPrecision": evaluation.tool_precision,
                "toolRecall": evaluation.tool_recall,
                "toolF1": evaluation.tool_f1,
                "nodeLabelSimilarity": evaluation.node_label_similarity,
                "structuralSimilarityIndex": evaluation.structural_similarity_index,
                "pathLengthSimilarity": evaluation.path_length_similarity,
                "complexityScore": evaluation.complexity_score,
                "notes": "|".join(evaluation.notes),
            }

            existing_metrics = metrics_by_id.get(challenge_id)
            if existing_metrics is None or metrics_row["structuralSimilarityIndex"] > existing_metrics["structuralSimilarityIndex"]:
                metrics_by_id[challenge_id] = metrics_row
                annotations_by_id[challenge_id] = annotation_entry

    output_root.mkdir(parents=True, exist_ok=True)

    annotations = list(annotations_by_id.values())
    metrics_table = list(metrics_by_id.values())

    annotations_path = output_root / "agentic_challenge_annotations.json"
    with annotations_path.open("w", encoding="utf-8") as handle:
        json.dump(annotations, handle, indent=2)

    metrics_path = output_root / "agentic_challenge_metrics.csv"
    if metrics_table:
        with metrics_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(metrics_table[0].keys()))
            writer.writeheader()
            writer.writerows(metrics_table)

    summary_path = output_root / "track_complexity_summary.md"
    _write_summary(metrics_table, summary_path)

    alignment_path = output_root / "paper_alignment_brief.md"
    write_alignment_brief(
        metrics_table,
        alignment_path,
        paper_path=Path("Advancing Agentic Systems Dynamic Task Decomposition Tool Integration and Evaluation using Novel Metrics and Dataset.pdf"),
    )

    return annotations, metrics_table


def _write_summary(metrics_table: List[Dict[str, Any]], summary_path: Path) -> None:
    if not metrics_table:
        summary_path.write_text("No challenges processed.\n", encoding="utf-8")
        return

    aggregates: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: Dict[str, int] = defaultdict(int)
    scenario_counts: Dict[str, Counter] = defaultdict(Counter)
    note_frequency: Dict[str, Counter] = defaultdict(Counter)

    for row in metrics_table:
        track = row.get("trackType") or "Unknown"
        counts[track] += 1
        scenario_counts[track][row.get("scenarioType") or "unknown"] += 1
        if row.get("notes"):
            for note in row["notes"].split("|"):
                if note:
                    note_frequency[track][note] += 1

        for metric in ("nodeF1", "edgeF1", "toolF1", "structuralSimilarityIndex", "pathLengthSimilarity", "complexityScore"):
            aggregates[track][metric] += float(row.get(metric, 0.0))

    lines: List[str] = []
    lines.append("# Track-Level Agentic Analysis Summary\n")
    lines.append("Derived from Advancing Agentic Systems-inspired evaluation metrics.\n")

    for track, total in counts.items():
        lines.append(f"## {track or 'Unknown'}")
        lines.append(f"- Challenges analysed: {total}")
        if total:
            for metric, value in aggregates[track].items():
                avg_value = value / total
                if metric == "complexityScore":
                    lines.append(f"- Avg complexity (|V|+|E|): {avg_value:.1f}")
                else:
                    lines.append(f"- Avg {metric}: {avg_value:.3f}")
        scenario_line = ", ".join(f"{scenario}: {count}" for scenario, count in scenario_counts[track].items())
        lines.append(f"- Scenario mix: {scenario_line or 'No data'}")
        top_notes = note_frequency[track].most_common(3)
        if top_notes:
            lines.append("- Frequent notes:")
            for note, freq in top_notes:
                lines.append(f"  - ({freq}) {note}")
        lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic framework analysis for Topcoder challenges.")
    parser.add_argument("--challenge-root", type=Path, default=Path("challenge_data"), help="Path containing downloaded challenge JSON files.")
    parser.add_argument("--output-root", type=Path, default=Path("analysis/advancing_agentic_systems/output"), help="Directory to store generated reports.")
    parser.add_argument("--fine-grained", action="store_true", help="Force fine-grained plans regardless of heuristics.")
    parser.add_argument("--include-incomplete", action="store_true", help="Include challenges missing IDs or metadata.")

    args = parser.parse_args()
    generate_reports(
        challenge_root=args.challenge_root,
        output_root=args.output_root,
        prefer_fine_grained=args.fine_grained,
        include_incomplete=args.include_incomplete,
    )


if __name__ == "__main__":
    main()

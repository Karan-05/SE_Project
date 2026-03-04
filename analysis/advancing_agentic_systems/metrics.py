"""Evaluation metrics mirroring the Advancing Agentic Systems paper."""

from __future__ import annotations

from dataclasses import asdict
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Mapping, Set, Tuple

from .models import (
    AgenticPlan,
    PlanEvaluation,
    TaskNode,
    normalize_label,
    normalize_tool,
    to_edge_set,
)


def _precision_recall_f1(pred_set: Set[str] | Set[Tuple[str, str]], gold_set: Set[str] | Set[Tuple[str, str]]) -> Tuple[float, float, float]:
    if not pred_set and not gold_set:
        return 1.0, 1.0, 1.0
    if not pred_set:
        return 0.0, 0.0 if gold_set else 1.0, 0.0
    if not gold_set:
        return 0.0, 1.0, 0.0
    tp = len(pred_set & gold_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(gold_set) if gold_set else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _label_set(plan: AgenticPlan) -> Set[str]:
    return {normalize_label(node.label) for node in plan.nodes.values()}


def _tool_pairs(plan: AgenticPlan) -> Set[Tuple[str, str]]:
    pairs: Set[Tuple[str, str]] = set()
    for node in plan.nodes.values():
        label = normalize_label(node.label)
        for tool in node.tools:
            pairs.add((label, normalize_tool(tool)))
    return pairs


def _edge_labels(plan: AgenticPlan) -> Set[Tuple[str, str]]:
    label_map = {node_id: normalize_label(node.label) for node_id, node in plan.nodes.items()}
    return {(label_map.get(src, src), label_map.get(dst, dst)) for src, dst in to_edge_set(plan.edges)}


def _node_label_similarity(pred_plan: AgenticPlan, gold_plan: AgenticPlan) -> float:
    gold_labels = list(_label_set(gold_plan))
    if not gold_labels:
        return 1.0
    total_score = 0.0
    for pred_label in _label_set(pred_plan):
        if not gold_labels:
            break
        best = max(SequenceMatcher(a=pred_label, b=gold_label).ratio() for gold_label in gold_labels)
        total_score += best
    if not _label_set(pred_plan):
        return 0.0
    return total_score / len(_label_set(pred_plan))


def _levels_by_label(plan: AgenticPlan) -> Dict[str, int]:
    indegree = plan.in_degree()
    adjacency = plan.adjacency()
    queue = [node_id for node_id, deg in indegree.items() if deg == 0]
    levels: Dict[str, int] = {}
    node_level: Dict[str, int] = {node_id: 0 for node_id in plan.nodes}

    while queue:
        current = queue.pop(0)
        current_level = node_level[current]
        for neighbor in adjacency.get(current, set()):
            proposed = current_level + 1
            if proposed > node_level.get(neighbor, 0):
                node_level[neighbor] = proposed
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                queue.append(neighbor)

    for node_id, level in node_level.items():
        label = normalize_label(plan.nodes[node_id].label)
        if label in levels:
            levels[label] = max(levels[label], level)
        else:
            levels[label] = level
    return levels


def _path_length_similarity(pred_plan: AgenticPlan, gold_plan: AgenticPlan) -> float:
    pred_levels = _levels_by_label(pred_plan)
    gold_levels = _levels_by_label(gold_plan)
    common_labels = set(pred_levels) & set(gold_levels)
    if not common_labels:
        return 0.0
    max_level_span = max(max(pred_levels.values(), default=0), max(gold_levels.values(), default=0))
    if max_level_span == 0:
        return 1.0
    total_diff = sum(abs(pred_levels[label] - gold_levels[label]) for label in common_labels)
    normalized_diff = total_diff / (len(common_labels) * max_level_span)
    return max(0.0, 1.0 - normalized_diff)


def evaluate_plan_against_baseline(
    plan: AgenticPlan,
    baseline_plan: AgenticPlan,
    baseline_id: str,
) -> PlanEvaluation:
    node_precision, node_recall, node_f1 = _precision_recall_f1(_label_set(plan), _label_set(baseline_plan))
    edge_precision, edge_recall, edge_f1 = _precision_recall_f1(_edge_labels(plan), _edge_labels(baseline_plan))
    tool_precision, tool_recall, tool_f1 = _precision_recall_f1(_tool_pairs(plan), _tool_pairs(baseline_plan))

    node_label_similarity = _node_label_similarity(plan, baseline_plan)
    ssi = (node_label_similarity + edge_f1) / 2.0
    path_similarity = _path_length_similarity(plan, baseline_plan)

    return PlanEvaluation(
        challenge_id=plan.challenge_id,
        baseline_id=baseline_id,
        node_precision=node_precision,
        node_recall=node_recall,
        node_f1=node_f1,
        edge_precision=edge_precision,
        edge_recall=edge_recall,
        edge_f1=edge_f1,
        tool_precision=tool_precision,
        tool_recall=tool_recall,
        tool_f1=tool_f1,
        node_label_similarity=node_label_similarity,
        structural_similarity_index=ssi,
        path_length_similarity=path_similarity,
        complexity_score=plan.complexity_score(),
        scenario_type=plan.scenario_type,
        granularity=plan.granularity,
        notes=tuple(plan.notes),
    )

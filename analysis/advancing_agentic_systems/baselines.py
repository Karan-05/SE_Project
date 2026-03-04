"""Baseline task graphs used as reference plans for evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .models import AgenticPlan, TaskEdge, TaskNode


@dataclass(frozen=True)
class BaselinePlan:
    baseline_id: str
    description: str
    plan: AgenticPlan


def _baseline_plan(challenge_stub: str, scenario_type: str, granularity: str, nodes, edges, notes=None) -> AgenticPlan:
    return AgenticPlan(
        challenge_id=challenge_stub,
        scenario_type=scenario_type,
        granularity=granularity,
        nodes={node.node_id: node for node in nodes},
        edges=list(edges),
        notes=list(notes or []),
    )


BASELINE_LIBRARY: Dict[str, BaselinePlan] = {}


def register_baseline(key: str, baseline: BaselinePlan) -> None:
    BASELINE_LIBRARY[key] = baseline


def get_baseline(key: str) -> BaselinePlan:
    return BASELINE_LIBRARY[key]


def list_baselines() -> Tuple[str, ...]:
    return tuple(BASELINE_LIBRARY.keys())


# Development sequential (coarse)
register_baseline(
    "dev_sequential_coarse",
    BaselinePlan(
        baseline_id="dev_sequential_coarse",
        description="Sequential delivery for development challenges with coarse tasks.",
        plan=_baseline_plan(
            challenge_stub="development_coarse",
            scenario_type="sequential",
            granularity="coarse",
            nodes=[
                TaskNode("n1", "Clarify requirements", ("SpecParser",), None),
                TaskNode("n2", "Establish environment", ("RepoCloner",), None),
                TaskNode("n3", "Implement solution", ("CodePilot",), None),
                TaskNode("n4", "Validate & test", ("TestMaestro", "RefactorGuard"), None),
                TaskNode("n5", "Package & handoff", ("DeploySage", "NarrativeWeaver"), None),
            ],
            edges=[
                TaskEdge("n1", "n2"),
                TaskEdge("n2", "n3"),
                TaskEdge("n3", "n4"),
                TaskEdge("n4", "n5"),
            ],
        ),
    ),
)

# Development (fine, with parallel testing)
register_baseline(
    "dev_parallel_fine",
    BaselinePlan(
        baseline_id="dev_parallel_fine",
        description="Fine-grained development plan with parallel QA/performance tasks.",
        plan=_baseline_plan(
            challenge_stub="development_fine",
            scenario_type="hybrid",
            granularity="fine",
            nodes=[
                TaskNode("n1", "Interrogate challenge brief", ("SpecParser", "TechRadar"), None),
                TaskNode("n2", "Bootstrap workspace", ("RepoCloner",), None),
                TaskNode("n3", "Design implementation approach", ("TechRadar",), "P1"),
                TaskNode("n4", "Code feature increments", ("CodePilot",), "P1"),
                TaskNode("n5", "Synthesize automated tests", ("TestMaestro",), "P2"),
                TaskNode("n6", "Run static and perf analysis", ("RefactorGuard", "BenchmarkBuddy"), "P2"),
                TaskNode("n7", "Perform integration verification", ("BenchmarkBuddy",), None),
                TaskNode("n8", "Finalize delivery packet", ("DeploySage", "NarrativeWeaver"), None),
            ],
            edges=[
                TaskEdge("n1", "n2"),
                TaskEdge("n2", "n3"),
                TaskEdge("n2", "n4"),
                TaskEdge("n3", "n4"),
                TaskEdge("n4", "n7"),
                TaskEdge("n3", "n5"),
                TaskEdge("n4", "n5"),
                TaskEdge("n5", "n7"),
                TaskEdge("n6", "n7"),
                TaskEdge("n7", "n8"),
            ],
        ),
    ),
)

# Design baseline
register_baseline(
    "design_parallel",
    BaselinePlan(
        baseline_id="design_parallel",
        description="Design-oriented flow with high parallel exploration.",
        plan=_baseline_plan(
            challenge_stub="design_parallel",
            scenario_type="parallel",
            granularity="fine",
            nodes=[
                TaskNode("n1", "Frame creative brief", ("SpecParser",), None),
                TaskNode("n2", "Research references", ("TechRadar",), "P1"),
                TaskNode("n3", "Generate concept variants", ("DesignStudio",), "P1"),
                TaskNode("n4", "Accessibility review", ("DesignStudio",), "P2"),
                TaskNode("n5", "Consolidate stakeholder-ready assets", ("NarrativeWeaver",), None),
            ],
            edges=[
                TaskEdge("n1", "n2"),
                TaskEdge("n1", "n3"),
                TaskEdge("n2", "n5"),
                TaskEdge("n3", "n4"),
                TaskEdge("n4", "n5"),
            ],
        ),
    ),
)

# Data science baseline
register_baseline(
    "data_science_hybrid",
    BaselinePlan(
        baseline_id="data_science_hybrid",
        description="Data science workflow balancing data prep, modelling, and validation tasks.",
        plan=_baseline_plan(
            challenge_stub="ds_hybrid",
            scenario_type="hybrid",
            granularity="fine",
            nodes=[
                TaskNode("n1", "Audit data assets", ("DataWrangler",), None),
                TaskNode("n2", "Profile problem statement", ("SpecParser", "TechRadar"), None),
                TaskNode("n3", "Engineer features", ("DataWrangler",), "P1"),
                TaskNode("n4", "Train baseline models", ("CodePilot",), "P1"),
                TaskNode("n5", "Evaluate metrics & fairness", ("BenchmarkBuddy",), "P2"),
                TaskNode("n6", "Publish report & artifacts", ("NarrativeWeaver",), None),
            ],
            edges=[
                TaskEdge("n1", "n3"),
                TaskEdge("n2", "n3"),
                TaskEdge("n3", "n4"),
                TaskEdge("n4", "n5"),
                TaskEdge("n5", "n6"),
            ],
        ),
    ),
)

# QA baseline
register_baseline(
    "qa_sequential",
    BaselinePlan(
        baseline_id="qa_sequential",
        description="Testing & QA heavy scenario with sequential gating.",
        plan=_baseline_plan(
            challenge_stub="qa_seq",
            scenario_type="sequential",
            granularity="coarse",
            nodes=[
                TaskNode("n1", "Decode regression scope", ("SpecParser",), None),
                TaskNode("n2", "Curate test matrix", ("TestMaestro",), None),
                TaskNode("n3", "Automate scenarios", ("CodePilot", "TestMaestro"), None),
                TaskNode("n4", "Analyse failures & craft report", ("RefactorGuard", "NarrativeWeaver"), None),
            ],
            edges=[
                TaskEdge("n1", "n2"),
                TaskEdge("n2", "n3"),
                TaskEdge("n3", "n4"),
            ],
        ),
    ),
)

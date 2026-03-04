"""Heuristic plan generator aligning Topcoder challenges with agentic workflows."""

from __future__ import annotations

import datetime as _dt
import itertools
from typing import Any, Dict, List, Tuple

from .models import AgenticPlan, TaskEdge, TaskNode
from .tool_catalog import tool_names


AI_KEYWORDS = (
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


def _tools(*candidates: str) -> Tuple[str, ...]:
    available = tool_names(candidates)
    return tuple(available)


def _estimate_duration(challenge: Dict[str, Any]) -> float:
    """Return approximate duration in days based on submission window."""
    start = challenge.get("registrationStartDate") or challenge.get("submissionStartDate")
    end = challenge.get("submissionEndDate") or challenge.get("endDate")
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        start_dt = _dt.datetime.strptime(start, fmt)
        end_dt = _dt.datetime.strptime(end, fmt)
        delta = end_dt - start_dt
        return max(delta.total_seconds() / 86400.0, 0.0)
    except Exception:
        return 0.0


def _parallel_group_generator(prefix: str):
    for idx in itertools.count(1):
        yield f"{prefix}{idx}"


def build_agentic_plan(
    challenge: Dict[str, Any],
    prefer_fine_grained: bool = False,
) -> AgenticPlan:
    """Generate a DAG plan reflecting the paper's orchestrator/delegator/executor stack."""

    track = (challenge.get("trackType") or challenge.get("track") or "").lower()
    challenge_type = (challenge.get("type") or "").lower()
    techs = [t.strip() for t in (challenge.get("technologies") or "").split(",") if t.strip()]
    duration_days = _estimate_duration(challenge)
    description = challenge.get("description") or ""
    title = challenge.get("name") or ""
    submissions = challenge.get("numOfSubmissions") or 0
    registrants = challenge.get("numOfRegistrants") or 0

    text_blob = " ".join([title, description, " ".join(techs)]).lower()
    is_ai_theme = any(keyword in text_blob for keyword in AI_KEYWORDS)
    should_use_data_plan = ("data" in track) or ("analytics" in track) or ("algo" in challenge_type) or is_ai_theme

    notes: List[str] = []

    def add_note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    # Determine granularity.
    if prefer_fine_grained:
        granularity = "fine"
        add_note("Forced fine-grained plan via CLI flag.")
    else:
        granularity = "fine" if duration_days > 4 or len(description) > 1200 or registrants > 25 else "coarse"

    # Determine scenario type (sequential / parallel / hybrid)
    if "design" in track or "design" in challenge_type:
        scenario_type = "parallel"
    elif "qa" in track or "test" in challenge_type:
        scenario_type = "sequential"
    elif len(techs) >= 4 or submissions > 10 or should_use_data_plan:
        scenario_type = "hybrid"
    else:
        scenario_type = "sequential"

    if should_use_data_plan:
        scenario_type = "hybrid"

    if scenario_type == "parallel" and granularity == "coarse":
        granularity = "fine"
        add_note("Design challenge coerced to fine granularity for richer branching.")

    if scenario_type == "hybrid" and granularity == "coarse":
        add_note("Hybrid scenario retains coarse granularity but adds selective branching.")

    nodes: List[TaskNode] = []
    edges: List[TaskEdge] = []
    pg = _parallel_group_generator("P")

    def add_node(node_id: str, label: str, tool_bundle: Tuple[str, ...], group: str | None = None):
        nodes.append(TaskNode(node_id=node_id, label=label, tools=tool_bundle, parallel_group=group))

    def connect(src: str, dst: str):
        edges.append(TaskEdge(source=src, target=dst))

    # Base skeleton per scenario/track
    if "design" in track:
        _build_design_plan(challenge, granularity, add_node, connect, pg, notes)
    elif "qa" in track or "test" in challenge_type:
        _build_qa_plan(challenge, granularity, add_node, connect, notes)
    elif should_use_data_plan:
        _build_data_science_plan(challenge, granularity, scenario_type, add_node, connect, pg, notes)
    else:
        _build_dev_plan(challenge, granularity, scenario_type, add_node, connect, pg, notes)

    # Risk-oriented annotations
    if submissions == 0 and scenario_type != "design":
        add_note("Zero submissions: emphasize exploratory tasks and fallbacks.")
    if duration_days < 1 and scenario_type == "sequential":
        add_note("Rapid-turn sequential workflow: plan focuses on correctness over exploration.")
    if len(techs) > 5:
        add_note("High technology breadth: ensure tool filtering prevents overload.")

    return AgenticPlan(
        challenge_id=challenge.get("challengeId") or challenge.get("id") or "unknown",
        scenario_type=scenario_type,
        granularity=granularity,
        nodes={node.node_id: node for node in nodes},
        edges=edges,
        notes=notes,
    )


def _build_dev_plan(challenge, granularity, scenario_type, add_node, connect, pg, notes):
    cid = challenge.get("challengeId", "dev")

    def add_local_note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    if scenario_type == "sequential":
        # Mirror dev_sequential_coarse baseline
        add_node("n1", "Clarify requirements", _tools("SpecParser"))
        add_node("n2", "Establish environment", _tools("RepoCloner"))
        add_node("n3", "Implement solution", _tools("CodePilot"))
        add_node("n4", "Validate & test", _tools("TestMaestro", "RefactorGuard"))
        add_node("n5", "Package & handoff", _tools("DeploySage", "NarrativeWeaver"))
        connect("n1", "n2")
        connect("n2", "n3")
        connect("n3", "n4")
        connect("n4", "n5")
        if challenge.get("numOfRegistrants", 0) > 30:
            add_local_note("High registrant count: inserted coordination checkpoint.")
    else:
        # Align with dev_parallel_fine baseline (hybrid/parallel workloads)
        add_node("n1", "Interrogate challenge brief", _tools("SpecParser", "TechRadar"))
        add_node("n2", "Bootstrap workspace", _tools("RepoCloner"))
        parallel_group_one = next(pg)
        add_node("n3", "Design implementation approach", _tools("TechRadar"), parallel_group_one)
        add_node("n4", "Code feature increments", _tools("CodePilot"), parallel_group_one)
        parallel_group_two = next(pg)
        add_node("n5", "Synthesize automated tests", _tools("TestMaestro"), parallel_group_two)
        add_node("n6", "Run static and perf analysis", _tools("RefactorGuard", "BenchmarkBuddy"), parallel_group_two)
        add_node("n7", "Perform integration verification", _tools("BenchmarkBuddy"))
        add_node("n8", "Finalize delivery packet", _tools("DeploySage", "NarrativeWeaver"))

        connect("n1", "n2")
        connect("n2", "n3")
        connect("n2", "n4")
        connect("n3", "n4")
        connect("n4", "n7")
        connect("n3", "n5")
        connect("n4", "n5")
        connect("n5", "n7")
        connect("n6", "n7")
        connect("n7", "n8")

        if challenge.get("numOfRegistrants", 0) > 30:
            add_local_note("High registrant count: inserted coordination checkpoint.")
        if len((challenge.get("technologies") or "").split(",")) > 4:
            add_local_note("High technology breadth: ensure tool filtering prevents overload.")


def _build_design_plan(challenge, granularity, add_node, connect, pg, notes):
    def add_note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    add_node("n1", "Frame creative brief", _tools("SpecParser"))
    parallel_concept = next(pg)
    add_node("n2", "Research references", _tools("TechRadar"), parallel_concept)
    add_node("n3", "Generate concept variants", _tools("DesignStudio"), parallel_concept)
    connect("n1", "n2")
    connect("n1", "n3")

    refinement_group = next(pg)
    add_node("n4", "Accessibility review", _tools("DesignStudio"), refinement_group)
    add_node("n5", "Peer critique loop", _tools("NarrativeWeaver"), refinement_group)
    connect("n2", "n4")
    connect("n3", "n4")
    connect("n3", "n5")
    connect("n4", "n6")
    connect("n5", "n6")

    add_node("n6", "Consolidate stakeholder-ready assets", _tools("NarrativeWeaver"))

    if granularity == "fine":
        add_node("n7", "Package implementation-ready specs", _tools("NarrativeWeaver"), None)
        connect("n6", "n7")

    if challenge.get("technologies"):
        add_note("Design brief references technologies, highlight close collaboration with developers.")


def _build_data_science_plan(challenge, granularity, scenario_type, add_node, connect, pg, notes):
    def add_note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    add_node("n1", "Audit data assets", _tools("DataWrangler"))
    add_node("n2", "Profile problem statement", _tools("SpecParser", "TechRadar"))

    feature_group = next(pg)
    add_node("n3", "Engineer features", _tools("DataWrangler"), feature_group)
    add_node("n4", "Train baseline models", _tools("CodePilot"), feature_group if scenario_type != "sequential" else None)
    connect("n1", "n3")
    connect("n2", "n3")
    connect("n3", "n4")

    eval_group = next(pg)
    add_node("n5", "Evaluate metrics & fairness", _tools("BenchmarkBuddy"), eval_group)
    add_node("n6", "Publish report & artifacts", _tools("NarrativeWeaver"), eval_group if granularity == "fine" else None)
    connect("n4", "n5")
    connect("n5", "n6")
    if granularity == "fine":
        connect("n4", "n6")

    if challenge.get("numOfSubmissions", 0) > 15:
        add_node("n7", "Scale hyperparameter exploration", _tools("CodePilot"), next(pg))
        connect("n4", "n7")
        connect("n7", "n5")
        add_note("High submission volume: added exploration branch for hyper-parameter sweep.")


def _build_qa_plan(challenge, granularity, add_node, connect, notes):
    def add_note(message: str) -> None:
        if message not in notes:
            notes.append(message)

    add_node("n1", "Decode regression scope", _tools("SpecParser"))
    add_node("n2", "Curate test matrix", _tools("TestMaestro"))
    connect("n1", "n2")

    add_node("n3", "Automate scenarios", _tools("CodePilot", "TestMaestro"))
    connect("n2", "n3")

    add_node("n4", "Analyse failures & craft report", _tools("RefactorGuard", "NarrativeWeaver"))
    connect("n3", "n4")

    if granularity == "fine":
        add_node("n5", "Coordinate fix handoff", _tools("DeploySage"), None)
        connect("n4", "n5")

    if (challenge.get("technologies") or "").lower().find("mobile") != -1:
        add_note("Mobile QA: emphasise device matrix coverage in coverage planning.")

"""Curated catalogue of agent/tools inspired by the Advancing Agentic Systems paper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set


@dataclass(frozen=True)
class Tool:
    """Representation of a callable tool or specialist agent."""

    name: str
    description: str
    tags: Set[str]
    parallel_safe: bool = True


def _tool(name: str, description: str, *tags: str, parallel_safe: bool = True) -> Tool:
    return Tool(name=name, description=description, tags=set(tags), parallel_safe=parallel_safe)


TOOL_REGISTRY: Dict[str, Tool] = {
    "SpecParser": _tool(
        "SpecParser",
        "LLM prompt template that extracts structured requirements, constraints, and acceptance criteria.",
        "analysis",
        "requirements",
        "sequential",
    ),
    "RepoCloner": _tool(
        "RepoCloner",
        "Automation agent that clones repositories, installs dependencies, and caches build artifacts.",
        "environment",
        "setup",
    ),
    "TechRadar": _tool(
        "TechRadar",
        "Embeddings-powered retrieval assistant that surfaces past implementations and tech decisions.",
        "research",
        "retrieval",
        "parallel",
    ),
    "CodePilot": _tool(
        "CodePilot",
        "Code-generation copilot tuned for Topcoder challenge stack patterns.",
        "implementation",
        "development",
        "parallel",
    ),
    "RefactorGuard": _tool(
        "RefactorGuard",
        "Static analysis harness that spots regressions, lint issues, and dependency drift.",
        "analysis",
        "testing",
    ),
    "TestMaestro": _tool(
        "TestMaestro",
        "Test synthesis agent producing unit/integration tests with coverage heatmaps.",
        "testing",
        "qa",
        "parallel",
    ),
    "BenchmarkBuddy": _tool(
        "BenchmarkBuddy",
        "Scenario simulator that executes benchmarks or rehearsal runs; yields perf snapshots.",
        "testing",
        "performance",
    ),
    "DeploySage": _tool(
        "DeploySage",
        "Release orchestration assistant handling packaging, approvals, and final verification.",
        "deployment",
        "sequential",
    ),
    "NarrativeWeaver": _tool(
        "NarrativeWeaver",
        "Documentation summariser that crafts delivery notes, changelog, and executive summaries.",
        "documentation",
        "communication",
        "parallel",
    ),
    "DesignStudio": _tool(
        "DesignStudio",
        "Generative design workspace for visual assets, mockups, and accessibility audits.",
        "design",
        "creative",
        "parallel",
    ),
    "DataWrangler": _tool(
        "DataWrangler",
        "Dataset ETL assistant that normalises, validates, and profiles data sources.",
        "data",
        "analysis",
        "parallel",
    ),
    "SkillProfiler": _tool(
        "SkillProfiler",
        "Agent that maps member handles to expertise vectors using stats/metadata.",
        "people",
        "analysis",
        "parallel",
    ),
}


def tools_by_tags(required_tags: Iterable[str]) -> List[Tool]:
    """Return tools whose tag set covers all required tags."""
    required = set(tag.lower() for tag in required_tags)
    matches: List[Tool] = []
    for tool in TOOL_REGISTRY.values():
        normalized_tags = {tag.lower() for tag in tool.tags}
        if required.issubset(normalized_tags):
            matches.append(tool)
    return matches


def tool_names(tool_ids: Iterable[str]) -> List[str]:
    return [tool_id for tool_id in tool_ids if tool_id in TOOL_REGISTRY]

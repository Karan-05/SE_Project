"""Contract generation for seeded repair tasks.

Each injected mutation yields a small, precise ContractItem that the CGCS
strategy can use as a clause to drive repair.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from .seeding import MutationFamily, SeedMutation


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

_FAMILY_CATEGORY: Dict[MutationFamily, str] = {
    MutationFamily.COMPARISON_FLIP: "boundary_condition",
    MutationFamily.INCORRECT_BOOLEAN: "logical_correctness",
    MutationFamily.OFF_BY_ONE: "off_by_one",
    MutationFamily.WRONG_RETURN: "return_value",
    MutationFamily.WRONG_FILTER: "filter_logic",
    MutationFamily.SORT_ORDER: "ordering",
    MutationFamily.WRONG_AGGREGATION_INIT: "aggregation",
    MutationFamily.MISSING_NULL_GUARD: "null_handling",
    MutationFamily.INCORRECT_DEDUP: "deduplication",
    MutationFamily.SWAPPED_FIELD: "field_selection",
}


def _mutation_id(mutation: SeedMutation, index: int) -> str:
    """Stable short identifier for a mutation."""
    digest = hashlib.sha256(
        f"{mutation.file_path}:{mutation.line_number}:{mutation.family}".encode()
    ).hexdigest()[:8]
    return f"M{index:03d}_{mutation.family.value}_{digest}"


def generate_contract_for_mutation(
    mutation: SeedMutation,
    index: int = 0,
    *,
    repo_key: str = "",
) -> Dict[str, Any]:
    """Return a single ContractItem dict for the given mutation."""
    clause_id = _mutation_id(mutation, index)
    category = _FAMILY_CATEGORY.get(mutation.family, "logical_correctness")
    description = (
        f"[{mutation.family.value}] In `{mutation.file_path}` (line {mutation.line_number}): "
        f"{mutation.description}. {mutation.expected_behavior}."
    )
    return {
        "id": clause_id,
        "label": mutation.expected_behavior[:80],
        "description": description,
        "category": category,
        "expected_behavior": mutation.expected_behavior,
        "tests": [],
        "keywords": [mutation.family.value, mutation.file_path, str(mutation.line_number)],
        "mutation_family": mutation.family.value,
        "mutation_file": mutation.file_path,
        "mutation_line": mutation.line_number,
        "repo_key": repo_key,
    }


def generate_contracts_for_mutations(
    mutations: List[SeedMutation],
    *,
    repo_key: str = "",
) -> List[Dict[str, Any]]:
    """Generate one ContractItem per mutation."""
    return [
        generate_contract_for_mutation(mut, idx, repo_key=repo_key)
        for idx, mut in enumerate(mutations)
    ]


def build_task_metadata(
    mutations: List[SeedMutation],
    contract_items: List[Dict[str, Any]],
    workspace_entry: Dict[str, Any],
    *,
    task_id: str,
    seed_patch_path: str | None = None,
) -> Dict[str, Any]:
    """Build the `metadata` block that goes inside a task.json file."""
    repo_key = str(workspace_entry.get("repo_key") or "")
    language = str(workspace_entry.get("language") or "python").lower()

    # candidate files = mutated files, deduplicated
    candidate_files = list(dict.fromkeys(m.file_path for m in mutations))

    metadata: Dict[str, Any] = {
        "task_id": task_id,
        "dataset": "public_repo_pilot",
        "dataset_source": "seeded_repair",
        "repo_key": repo_key,
        "language": language,
        "contract": contract_items,
        "implementation_target_files": candidate_files,
        "repo_target_files": candidate_files,
        "candidate_files": candidate_files,
        "mutations": [
            {
                "file_path": m.file_path,
                "line_number": m.line_number,
                "family": m.family.value,
                "description": m.description,
                "expected_behavior": m.expected_behavior,
                "original_line": m.original_line.rstrip("\n"),
                "mutated_line": m.mutated_line.rstrip("\n"),
            }
            for m in mutations
        ],
        "install_command": workspace_entry.get("install_command", ""),
        "build_command": workspace_entry.get("build_command", ""),
        "test_command": workspace_entry.get("test_command", ""),
        "runnable_confidence": workspace_entry.get("runnable_confidence", 0.0),
        "seeded_task": True,
    }
    if seed_patch_path:
        metadata["oracle_restore_info"] = {
            "patch_path": seed_patch_path,
            "mutation_count": len(mutations),
        }
    return metadata

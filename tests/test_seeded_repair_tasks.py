"""Tests for the seeded repair task generation modules."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.decomposition.public_repo_tasks.seeding import (
    MutationFamily,
    SeedMutation,
    find_mutation_candidates,
    apply_mutation,
    revert_mutation,
    generate_unified_diff,
    _try_comparison_flip,
    _try_incorrect_boolean,
    _try_off_by_one,
    _try_wrong_return,
    _try_sort_order,
    _try_wrong_aggregation_init,
    _try_missing_null_guard,
    _try_incorrect_dedup,
    _try_swapped_field,
)
from src.decomposition.public_repo_tasks.contracts import (
    generate_contract_for_mutation,
    generate_contracts_for_mutations,
    build_task_metadata,
)


# ---------------------------------------------------------------------------
# Seeding unit tests
# ---------------------------------------------------------------------------

def test_comparison_flip_gt():
    result = _try_comparison_flip("    if x > 0:\n")
    assert result is not None
    mutated, desc, expected = result
    assert ">=" in mutated
    assert ">" in desc


def test_comparison_flip_lte():
    result = _try_comparison_flip("    while i <= n:\n")
    assert result is not None
    mutated, _, _ = result
    assert "<" in mutated and "<=" not in mutated


def test_boolean_flip_true():
    result = _try_incorrect_boolean("    return True\n")
    assert result is not None
    mutated, _, _ = result
    assert "False" in mutated


def test_boolean_flip_false():
    result = _try_incorrect_boolean("    found = False\n")
    assert result is not None
    mutated, _, _ = result
    assert "True" in mutated


def test_off_by_one_plus():
    result = _try_off_by_one("    idx = start + 1\n")
    assert result is not None
    mutated, _, _ = result
    assert "+ 2" in mutated


def test_wrong_return_true():
    result = _try_wrong_return("    return True\n")
    assert result is not None
    mutated, _, _ = result
    assert "False" in mutated


def test_wrong_return_zero():
    result = _try_wrong_return("    return 0\n")
    assert result is not None
    mutated, _, _ = result
    assert "1" in mutated


def test_sort_order_detector():
    line = "items.sort(reverse=True)\n"
    mutated = _try_sort_order(line)
    assert mutated is not None
    m_line, _, expected = mutated
    assert "False" in m_line
    assert "reverse=True" in expected


def test_wrong_aggregation_init_detector():
    line = "totals = []\n"
    mutated = _try_wrong_aggregation_init(line)
    assert mutated is not None
    m_line, _, expected = mutated
    assert "{}" in m_line
    assert "[]" in expected


def test_missing_null_guard_detector():
    line = "if value is None:\n"
    mutated = _try_missing_null_guard(line)
    assert mutated is not None
    m_line, _, _ = mutated
    assert "is not None" in m_line


def test_incorrect_dedup_detector():
    line = "if row not in seen:\n"
    mutated = _try_incorrect_dedup(line)
    assert mutated is not None
    m_line, _, _ = mutated
    assert "in seen" in m_line and "not" not in m_line


def test_swapped_field_detector():
    line = "record['id'] = payload['id']\n"
    mutated = _try_swapped_field(line)
    assert mutated is not None
    m_line, _, _ = mutated
    assert "['name']" in m_line


def test_find_mutation_candidates_python(tmp_path):
    src = tmp_path / "module" / "solver.py"
    src.parent.mkdir()
    src.write_text(
        "def solve(n):\n"
        "    if n > 0:\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )
    candidates = find_mutation_candidates(tmp_path, max_per_file=5, max_total=5, rng_seed=0)
    assert len(candidates) > 0
    for c in candidates:
        assert c.file_path.endswith(".py")


def test_apply_and_revert_mutation(tmp_path):
    src = tmp_path / "src.py"
    src.write_text("def f():\n    return True\n", encoding="utf-8")
    mut = SeedMutation(
        file_path="src.py",
        line_number=2,
        original_line="    return True\n",
        mutated_line="    return False\n",
        family=MutationFamily.WRONG_RETURN,
        description="return True → False",
        expected_behavior="Should return True",
    )
    apply_mutation(tmp_path, mut, backup=True)
    assert "False" in src.read_text()
    revert_mutation(tmp_path, mut)
    assert "True" in src.read_text()
    assert "False" not in src.read_text()


def test_generate_unified_diff(tmp_path):
    src = tmp_path / "src.py"
    src.write_text("def f():\n    return True\n", encoding="utf-8")
    mut = SeedMutation(
        file_path="src.py",
        line_number=2,
        original_line="    return True\n",
        mutated_line="    return False\n",
        family=MutationFamily.WRONG_RETURN,
        description="test",
        expected_behavior="test",
    )
    diff = generate_unified_diff(tmp_path, mut)
    assert "--- a/src.py" in diff
    assert "+++ b/src.py" in diff
    assert "-    return True" in diff
    assert "+    return False" in diff


# ---------------------------------------------------------------------------
# Contract generation tests
# ---------------------------------------------------------------------------

def test_generate_contract_for_mutation():
    mut = SeedMutation(
        file_path="a/b.py",
        line_number=10,
        original_line="    if x > 0:\n",
        mutated_line="    if x >= 0:\n",
        family=MutationFamily.COMPARISON_FLIP,
        description="Changed > to >=",
        expected_behavior="Should use > not >=",
    )
    item = generate_contract_for_mutation(mut, index=0, repo_key="github.com/x/y")
    assert item["id"].startswith("M000_comparison_flip_")
    assert item["category"] == "boundary_condition"
    assert "github.com/x/y" in item["repo_key"]
    assert "a/b.py" in item["description"]


def test_generate_contracts_for_mutations():
    muts = [
        SeedMutation("a.py", 1, "x\n", "y\n", MutationFamily.INCORRECT_BOOLEAN, "d", "e"),
        SeedMutation("b.py", 2, "p\n", "q\n", MutationFamily.OFF_BY_ONE, "d2", "e2"),
    ]
    items = generate_contracts_for_mutations(muts, repo_key="github.com/a/b")
    assert len(items) == 2
    assert items[0]["id"] != items[1]["id"]


def test_build_task_metadata():
    muts = [
        SeedMutation("src/main.py", 5, "old\n", "new\n", MutationFamily.WRONG_RETURN, "d", "e")
    ]
    items = generate_contracts_for_mutations(muts)
    entry = {"repo_key": "github.com/x/y", "language": "Python", "runnable_confidence": 0.9}
    meta = build_task_metadata(muts, items, entry, task_id="test_task_001", seed_patch_path="/tmp/seed.patch")
    assert meta["task_id"] == "test_task_001"
    assert meta["seeded_task"] is True
    assert "src/main.py" in meta["candidate_files"]
    assert len(meta["contract"]) == 1
    assert len(meta["mutations"]) == 1
    assert meta["oracle_restore_info"]["patch_path"] == "/tmp/seed.patch"

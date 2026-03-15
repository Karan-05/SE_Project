"""Safe deterministic bug-injection (seeding) for repo-backed repair tasks.

All mutations are text-level (regex/string) so they work without executing the
code.  Only *source* files are mutated; test/config/lock files are skipped.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Mutation families
# ---------------------------------------------------------------------------

class MutationFamily(str, Enum):
    WRONG_FILTER = "wrong_filter_predicate"
    SORT_ORDER = "sort_order_inversion"
    OFF_BY_ONE = "off_by_one_offset"
    WRONG_AGGREGATION_INIT = "wrong_aggregation_init"
    MISSING_NULL_GUARD = "missing_null_guard"
    INCORRECT_DEDUP = "incorrect_dedup_condition"
    SWAPPED_FIELD = "swapped_field_usage"
    INCORRECT_BOOLEAN = "incorrect_boolean_condition"
    COMPARISON_FLIP = "comparison_flip"
    WRONG_RETURN = "wrong_return"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SeedMutation:
    """A single safe mutation that can be applied to a source file."""

    file_path: str          # relative to repo root
    line_number: int        # 1-based
    original_line: str      # exact original text
    mutated_line: str       # replacement text
    family: MutationFamily
    description: str        # human-readable description for contract generation
    expected_behavior: str  # what the correct code does


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------

_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".pytest_cache",
    "dist", "build", "target", ".tox", "venv", ".venv", "env",
}

_SOURCE_EXTS = {".py", ".js", ".ts", ".java", ".jsx", ".tsx", ".mjs", ".cjs"}

_TEST_NAME_PATTERNS = re.compile(
    r"(^test_|_test\.|\.spec\.|\.test\.|/tests?/|/spec/|/__tests__/|"
    r"Test\.java$|Tests\.java$)",
    re.IGNORECASE,
)


def _is_source_file(rel_path: Path) -> bool:
    parts = rel_path.parts
    for part in parts[:-1]:
        if part.lower() in _SKIP_DIRS:
            return False
    name = rel_path.name.lower()
    if rel_path.suffix.lower() not in _SOURCE_EXTS:
        return False
    if _TEST_NAME_PATTERNS.search(str(rel_path)):
        return False
    if name.startswith("."):
        return False
    return True


def _enumerate_source_files(repo_path: Path) -> List[Path]:
    sources: List[Path] = []
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(repo_path)
        except ValueError:
            continue
        if _is_source_file(rel):
            sources.append(rel)
    return sorted(sources)


# ---------------------------------------------------------------------------
# Mutation detectors (one per family)
# ---------------------------------------------------------------------------

# comparison_flip: > → >=, >= → >, < → <=, <= → <
_CMP_PATTERN = re.compile(r"(?<![=!<>])([><=!]=?)(?![>=])")

_CMP_FLIP: dict[str, str] = {
    ">": ">=",
    ">=": ">",
    "<": "<=",
    "<=": "<",
}


def _try_comparison_flip(line: str) -> Optional[Tuple[str, str, str]]:
    """Return (mutated_line, description, expected_behavior) or None."""
    for op, replacement in _CMP_FLIP.items():
        # avoid touching == or !=
        if op in ("==", "!=", "="):
            continue
        # use word-boundary-like check: operator not preceded by = or !
        pattern = re.compile(r"(?<![=!<>])" + re.escape(op) + r"(?![>=])")
        if pattern.search(line):
            mutated = pattern.sub(replacement, line, count=1)
            if mutated != line:
                return (
                    mutated,
                    f"Comparison operator changed from `{op}` to `{replacement}`",
                    f"Should use `{op}` (not `{replacement}`) for correct boundary check",
                )
    return None


# incorrect_boolean_condition: `and` ↔ `or`, `True` ↔ `False`
def _try_incorrect_boolean(line: str) -> Optional[Tuple[str, str, str]]:
    m = re.search(r"\bTrue\b", line)
    if m:
        mutated = line[:m.start()] + "False" + line[m.end():]
        return mutated, "Boolean literal changed from `True` to `False`", "Should be `True`"
    m = re.search(r"\bFalse\b", line)
    if m:
        mutated = line[:m.start()] + "True" + line[m.end():]
        return mutated, "Boolean literal changed from `False` to `True`", "Should be `False`"
    m = re.search(r"\band\b", line)
    if m:
        mutated = line[:m.start()] + "or" + line[m.end():]
        return mutated, "Logical operator changed from `and` to `or`", "Should use `and`"
    return None


# off_by_one: + 1 → + 2, - 1 → - 2 (integer literal offsets)
_OFF_BY_ONE_PAT = re.compile(r"([+\-])\s*1\b")


def _try_off_by_one(line: str) -> Optional[Tuple[str, str, str]]:
    m = _OFF_BY_ONE_PAT.search(line)
    if not m:
        return None
    op = m.group(1)
    mutated = line[:m.start()] + op + " 2" + line[m.end():]
    return (
        mutated,
        f"Off-by-one: `{op} 1` changed to `{op} 2`",
        f"Should be `{op} 1` (not `{op} 2`)",
    )


# wrong_return: flip the return value on a simple single-value return
_RETURN_PAT = re.compile(r"^(\s*return\s+)(True|False|0|1|-1|None|null|\"\")\s*$")

_RETURN_FLIP: dict[str, str] = {
    "True": "False",
    "False": "True",
    "0": "1",
    "1": "0",
    "-1": "0",
    "None": "None",       # skip None → None
    "null": "null",       # skip null → null
    '""': '""',           # skip empty → empty
}


def _try_wrong_return(line: str) -> Optional[Tuple[str, str, str]]:
    m = _RETURN_PAT.match(line)
    if not m:
        return None
    prefix, value = m.group(1), m.group(2)
    replacement = _RETURN_FLIP.get(value)
    if replacement is None or replacement == value:
        return None
    mutated = prefix + replacement + "\n" if line.endswith("\n") else prefix + replacement
    return (
        mutated,
        f"Return value changed from `{value}` to `{replacement}`",
        f"Should return `{value}` (not `{replacement}`)",
    )


# wrong_filter: invert a filter/guard condition by wrapping with `not`
_FILTER_PAT = re.compile(r"\bif\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s*(?=[:\{]|$)")


def _try_wrong_filter(line: str) -> Optional[Tuple[str, str, str]]:
    m = _FILTER_PAT.search(line)
    if not m:
        return None
    expr = m.group(1)
    mutated = line[:m.start()] + f"if not {expr}" + line[m.end():]
    return (
        mutated,
        f"Filter condition inverted: `if {expr}` → `if not {expr}`",
        f"Condition should be truthy (not negated): `if {expr}`",
    )


# sort_order_inversion: toggle reverse flag on `.sort`/`sorted` calls
_SORT_REVERSE_CALL = re.compile(r"(reverse\s*=\s*)(True|False)", re.IGNORECASE)
_SORT_FUNC_CALL = re.compile(r"(\.sort\()([^)]*)(\))")
_SORTED_CALL = re.compile(r"(sorted\()([^)]*)(\))")


def _toggle_reverse(value: str) -> str:
    return "False" if value.lower() == "true" else "True"


def _inject_reverse(args: str) -> str:
    args = args.strip()
    if not args:
        return "reverse=True"
    return f"{args}, reverse=True"


def _try_sort_order(line: str) -> Optional[Tuple[str, str, str]]:
    m = _SORT_REVERSE_CALL.search(line)
    if m:
        original = m.group(2)
        replacement = _toggle_reverse(original)
        mutated = line[: m.start(2)] + replacement + line[m.end(2) :]
        return (
            mutated,
            f"Sort order reversed: `reverse={original}` → `reverse={replacement}`",
            f"Should keep `reverse={original}` for correct ordering",
        )
    for pattern in (_SORT_FUNC_CALL, _SORTED_CALL):
        m = pattern.search(line)
        if not m or "reverse=" in m.group(2):
            continue
        args = m.group(2)
        new_args = _inject_reverse(args)
        mutated = line[: m.start(2)] + new_args + line[m.end(2) :]
        return (
            mutated,
            "Missing reverse flag inserted (forces descending order)",
            "Should maintain ascending order (no reverse flag)",
        )
    return None


# wrong_aggregation_init: change accumulator initial value
_AGG_INIT_PATTERN = re.compile(r"^(\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*)(\[\]|\{\}|set\(\)|0|1)")


def _try_wrong_aggregation_init(line: str) -> Optional[Tuple[str, str, str]]:
    m = _AGG_INIT_PATTERN.match(line)
    if not m:
        return None
    prefix, value = m.group(1), m.group(2)
    replacements = {
        "[]": "{}",
        "{}": "[]",
        "set()": "[]",
        "0": "1",
        "1": "0",
    }
    replacement = replacements.get(value)
    if not replacement:
        return None
    mutated = prefix + replacement + ("\n" if line.endswith("\n") else "")
    return (
        mutated,
        f"Aggregation init changed from `{value}` to `{replacement}`",
        f"Should initialize accumulator with `{value}`",
    )


# missing_null_guard: flip `is None` to `is not None`
_NULL_GUARD_PATTERN = re.compile(r"(is\s+None|==\s*None)")


def _try_missing_null_guard(line: str) -> Optional[Tuple[str, str, str]]:
    m = _NULL_GUARD_PATTERN.search(line)
    if not m:
        return None
    original = m.group(1)
    if "==" in original:
        replacement = "!= None"
    else:
        replacement = "is not None"
    mutated = line[: m.start(1)] + replacement + line[m.end(1) :]
    return (
        mutated,
        f"Null guard flipped: `{original}` → `{replacement}`",
        "Should guard for missing/null values",
    )


# incorrect_dedup_condition: change `not in` to `in`
_DEDUP_PATTERN = re.compile(r"\bnot\s+in\b")


def _try_incorrect_dedup(line: str) -> Optional[Tuple[str, str, str]]:
    m = _DEDUP_PATTERN.search(line)
    if not m:
        return None
    mutated = line[: m.start()] + "in" + line[m.end() :]
    return (
        mutated,
        "`not in` condition changed to `in` (dedup check inverted)",
        "Should use `not in` to avoid duplicates",
    )


# swapped_field_usage: swap common column name
_FIELD_SWAP = {
    "id": "name",
    "name": "id",
    "start": "end",
    "end": "start",
    "min": "max",
    "max": "min",
    "left": "right",
    "right": "left",
}
_FIELD_PATTERN = re.compile(r"(\[\s*['\"](?P<key>\w+)['\"]\s*\])|(\.get\(\s*['\"](?P<gkey>\w+)['\"]\s*\))")


def _try_swapped_field(line: str) -> Optional[Tuple[str, str, str]]:
    m = _FIELD_PATTERN.search(line)
    if not m:
        return None
    key = m.group("key") or m.group("gkey")
    replacement = _FIELD_SWAP.get(key)
    if not replacement:
        return None
    segment = line[m.start():m.end()]
    mutated_segment = segment.replace(key, replacement, 1)
    mutated = line[: m.start()] + mutated_segment + line[m.end() :]
    return (
        mutated,
        f"Field usage swapped: `{key}` → `{replacement}`",
        f"Should reference `{key}`",
    )


_DETECTORS = [
    (MutationFamily.SORT_ORDER, _try_sort_order),
    (MutationFamily.WRONG_AGGREGATION_INIT, _try_wrong_aggregation_init),
    (MutationFamily.MISSING_NULL_GUARD, _try_missing_null_guard),
    (MutationFamily.INCORRECT_DEDUP, _try_incorrect_dedup),
    (MutationFamily.SWAPPED_FIELD, _try_swapped_field),
    (MutationFamily.OFF_BY_ONE, _try_off_by_one),
    (MutationFamily.INCORRECT_BOOLEAN, _try_incorrect_boolean),
    (MutationFamily.WRONG_FILTER, _try_wrong_filter),
    (MutationFamily.COMPARISON_FLIP, _try_comparison_flip),
    (MutationFamily.WRONG_RETURN, _try_wrong_return),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_mutation_candidates(
    repo_path: Path,
    *,
    max_per_file: int = 2,
    max_total: int = 10,
    rng_seed: int = 0,
) -> List[SeedMutation]:
    """Scan repo source files and return a list of safe mutation candidates.

    Candidates are ordered deterministically by (file, line).
    """
    import random
    rng = random.Random(rng_seed)

    source_files = _enumerate_source_files(repo_path)
    rng.shuffle(source_files)

    candidates: List[SeedMutation] = []
    seen_files: set[str] = set()

    for rel in source_files:
        if len(candidates) >= max_total:
            break
        abs_path = repo_path / rel
        try:
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            continue

        file_candidates: List[SeedMutation] = []
        for lineno, raw_line in enumerate(lines, start=1):
            for family, detector in _DETECTORS:
                result = detector(raw_line)
                if result is None:
                    continue
                mutated_line, description, expected = result
                if mutated_line == raw_line:
                    continue
                file_candidates.append(
                    SeedMutation(
                        file_path=rel.as_posix(),
                        line_number=lineno,
                        original_line=raw_line,
                        mutated_line=mutated_line,
                        family=family,
                        description=description,
                        expected_behavior=expected,
                    )
                )
                break  # at most one mutation per line

        if file_candidates:
            rng.shuffle(file_candidates)
            for mut in file_candidates[:max_per_file]:
                candidates.append(mut)
                if len(candidates) >= max_total:
                    break

    # stable sort by (file, line) for determinism
    candidates.sort(key=lambda m: (m.file_path, m.line_number))
    return candidates


def apply_mutation(repo_path: Path, mutation: SeedMutation, *, backup: bool = True) -> Path:
    """Apply a mutation to the file, optionally creating a `.orig` backup.

    Returns the path to the modified file.
    """
    abs_path = repo_path / mutation.file_path
    lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    idx = mutation.line_number - 1
    if idx < 0 or idx >= len(lines):
        raise IndexError(f"Line {mutation.line_number} out of range in {mutation.file_path}")
    if backup:
        backup_path = abs_path.with_suffix(abs_path.suffix + ".orig")
        if not backup_path.exists():
            shutil.copy2(abs_path, backup_path)
    # Preserve trailing newline style
    mutated = mutation.mutated_line
    if lines[idx].endswith("\n") and not mutated.endswith("\n"):
        mutated = mutated + "\n"
    lines[idx] = mutated
    abs_path.write_text("".join(lines), encoding="utf-8")
    return abs_path


def revert_mutation(repo_path: Path, mutation: SeedMutation) -> None:
    """Revert a mutation by restoring the `.orig` backup if present."""
    abs_path = repo_path / mutation.file_path
    backup_path = abs_path.with_suffix(abs_path.suffix + ".orig")
    if backup_path.exists():
        shutil.copy2(backup_path, abs_path)
        backup_path.unlink()
    else:
        # Write the original line directly
        lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        idx = mutation.line_number - 1
        if 0 <= idx < len(lines):
            orig = mutation.original_line
            if lines[idx].endswith("\n") and not orig.endswith("\n"):
                orig = orig + "\n"
            lines[idx] = orig
            abs_path.write_text("".join(lines), encoding="utf-8")


def generate_unified_diff(repo_path: Path, mutation: SeedMutation) -> str:
    """Generate a unified diff string for a mutation (without applying it)."""
    import difflib
    abs_path = repo_path / mutation.file_path
    original = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    mutated = list(original)
    idx = mutation.line_number - 1
    mutated_line = mutation.mutated_line
    if original[idx].endswith("\n") and not mutated_line.endswith("\n"):
        mutated_line = mutated_line + "\n"
    mutated[idx] = mutated_line
    diff = list(difflib.unified_diff(
        original, mutated,
        fromfile=f"a/{mutation.file_path}",
        tofile=f"b/{mutation.file_path}",
    ))
    return "".join(diff)

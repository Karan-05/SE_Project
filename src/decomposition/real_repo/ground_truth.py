"""Helpers for parsing ground-truth patches for localization metrics."""
from __future__ import annotations

from pathlib import Path
from typing import List, Set

from src.config import PROJECT_ROOT


def _parse_patch_paths(text: str) -> List[str]:
    files: Set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("+++ "):
            target = stripped[4:].strip()
            if target.startswith("a/") or target.startswith("b/"):
                target = target[2:]
            if not target or target == "/dev/null" or target.startswith("/tmp/"):
                continue
            files.add(target)
        elif stripped.startswith("*** Add File: "):
            target = stripped[len("*** Add File: ") :].strip()
            if target:
                files.add(target)
    return sorted(files)


def load_ground_truth_files(patch_path: str | Path) -> List[str]:
    """Return the set of target files mentioned in a ground_truth.patch."""

    if not patch_path:
        return []
    path = Path(patch_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _parse_patch_paths(text)


__all__ = ["load_ground_truth_files"]

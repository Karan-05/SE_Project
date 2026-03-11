#!/usr/bin/env python3
"""Restore oversized artifacts that are stored compressed in git.

GitHub blocks files larger than 100 MB, so we commit .gz archives and unpack on
first run. Run this script once after cloning to materialize the canonical CSV
and JSON snapshots that downstream tooling expects.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path
from typing import Iterable, Tuple

Asset = Tuple[Path, Path, str]

ASSETS: Iterable[Asset] = [
    (
        Path("challenge_data/legacy_excel/challengeData_legacy_xlsx/page1.json.gz"),
        Path("challenge_data/legacy_excel/challengeData_legacy_xlsx/page1.json"),
        "Legacy Excel Topcoder challenge dump",
    ),
    (
        Path("data/processed/tasks.csv.gz"),
        Path("data/processed/tasks.csv"),
        "Processed Topcoder challenge table (22,023 rows)",
    ),
]


def unpack_asset(src: Path, dest: Path, label: str) -> None:
    """Inflate ``src`` into ``dest`` if needed."""

    if dest.exists():
        print(f"[skip] {label} already present at {dest}")
        return
    if not src.exists():
        print(f"[warn] Missing archive {src}; cannot restore {label}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(src, "rb") as gz_file, dest.open("wb") as out_file:
        shutil.copyfileobj(gz_file, out_file)
    print(f"[done] Restored {label} to {dest}")


def main() -> None:
    for src, dest, label in ASSETS:
        unpack_asset(src, dest, label)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Inspect normalized batch error outputs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import load_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug normalized batch errors.")
    parser.add_argument(
        "--errors-file",
        type=Path,
        default=Path("openai_artifacts/normalized/latest_errors.jsonl"),
        help="Path to normalized error JSONL file.",
    )
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()

    if not args.errors_file.exists():
        raise FileNotFoundError(f"No error file found at {args.errors_file}")
    rows = load_jsonl(args.errors_file)
    if not rows:
        print("No error rows detected.")
        return
    counter = Counter(row.get("error_code", "unknown") for row in rows)
    grouped: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        code = row.get("error_code", "unknown")
        custom_id = row.get("custom_id") or row.get("raw", {}).get("custom_id")
        if custom_id:
            grouped[code].append(str(custom_id))
    print("=== Batch Error Breakdown ===")
    for code, count in counter.most_common():
        print(f"- {code}: {count}")
    print("\n=== Sample Request IDs ===")
    for code, ids in list(grouped.items())[: args.top_n]:
        preview = ", ".join(ids[:5])
        print(f"{code}: {preview}")


if __name__ == "__main__":
    main()

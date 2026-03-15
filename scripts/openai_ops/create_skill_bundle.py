#!/usr/bin/env python3
"""Package CGCS repair skills into a portable bundle description."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import ensure_dir, utc_timestamp


def load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a reusable CGCS skill bundle.")
    parser.add_argument("--skill-card", type=Path, default=Path("skills/cgcs_skill.md"))
    parser.add_argument("--examples", type=Path, default=Path("skills/cgcs_examples.jsonl"))
    parser.add_argument("--constraints", type=Path, default=Path("skills/cgcs_constraints.json"))
    parser.add_argument("--output", type=Path, default=Path("openai_artifacts/skills/cgcs_skill_bundle.json"))
    args = parser.parse_args()

    bundle = {
        "skill_id": "cgcs_repair",
        "timestamp": utc_timestamp(),
        "card": load_text(args.skill_card),
        "examples_path": str(args.examples),
        "constraints": load_json(args.constraints),
    }
    ensure_dir(args.output.parent)
    args.output.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"Wrote skill bundle descriptor to {args.output}")


if __name__ == "__main__":
    main()

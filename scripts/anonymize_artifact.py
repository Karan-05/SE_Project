#!/usr/bin/env python3
"""Anonymize CGCS artifacts for external sharing."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict


def _anonymize_record(record: Dict[str, object]) -> Dict[str, object]:
    task_id = str(record.get("task_id") or "")
    task_hash = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:16]
    updated = dict(record)
    updated["task_id"] = task_hash
    updated["task_id_hash"] = task_hash
    updated["raw_edit_payload"] = "<redacted>"
    updated["context_snippets"] = []
    return updated


def _process_file(source: Path, destination: Path) -> int:
    if not source.exists():
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with source.open("r", encoding="utf-8") as inp, destination.open("w", encoding="utf-8") as out:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            anonymized = _anonymize_record(record)
            out.write(json.dumps(anonymized, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Anonymize CGCS dataset artifacts.")
    parser.add_argument("--source", type=Path, default=Path("data") / "cgcs", help="Source dataset directory.")
    parser.add_argument("--dest", type=Path, default=Path("artifacts") / "cgcs_anonymized", help="Destination directory.")
    args = parser.parse_args()
    total = 0
    for split in ("train", "dev", "test"):
        src = args.source / f"{split}.jsonl"
        dst = args.dest / f"{split}.jsonl"
        total += _process_file(src, dst)
    print(f"Anonymized {total} records into {args.dest}")


if __name__ == "__main__":
    main()

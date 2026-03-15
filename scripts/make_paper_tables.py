#!/usr/bin/env python3
"""Generate CGCS summary tables for the ASE paper."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List

from src.config import PathConfig


def _load_records(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _average(values: Iterable[float]) -> float:
    total = 0.0
    count = 0
    for value in values:
        total += value
        count += 1
    return total / count if count else 0.0


def build_tables(dataset_dir: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / "cgcs_table_main.csv"
    fieldnames = ["split", "attempts", "avg_pass_rate", "avg_witness_count", "regression_guard_rate", "oracle_patch_rate"]
    with table_path.open("w", encoding="utf-8", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for split in ("train", "dev", "test"):
            records = _load_records(dataset_dir / f"{split}.jsonl")
            if not records:
                continue
            pass_rates = [
                float(record.get("outcome_metrics", {}).get("pass_rate") or 0.0) for record in records
            ]
            witness_counts = [float(len(record.get("witnesses") or [])) for record in records]
            guard_hits = sum(1 for record in records if record.get("regression_guard_ids"))
            oracle_hits = sum(1 for record in records if record.get("oracle_patch_present"))
            writer.writerow(
                {
                    "split": split,
                    "attempts": len(records),
                    "avg_pass_rate": f"{_average(pass_rates):.3f}",
                    "avg_witness_count": f"{_average(witness_counts):.2f}",
                    "regression_guard_rate": f"{guard_hits / len(records):.3f}",
                    "oracle_patch_rate": f"{oracle_hits / len(records):.3f}",
                }
            )
    return table_path


def main() -> None:  # pragma: no cover
    dataset_dir = Path("data") / "cgcs"
    output_dir = PathConfig().reports_root / "ase2026_aegis"
    table_path = build_tables(dataset_dir, output_dir)
    print(f"Wrote CGCS table to {table_path}")


if __name__ == "__main__":
    main()

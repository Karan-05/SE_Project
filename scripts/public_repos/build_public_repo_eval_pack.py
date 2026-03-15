#!/usr/bin/env python3
"""Build eval items sourced from the public-repo pilot strict dataset rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.decomposition.openai_ops import EvalItem


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _iter_strict_rows(input_dir: Path) -> Iterable[Dict[str, Any]]:
    for split in ("train", "dev", "test"):
        for row in _load_jsonl(input_dir / f"{split}.jsonl"):
            row["_split"] = split
            yield row


def build_pilot_eval_items(input_dir: Path) -> List[EvalItem]:
    items: List[EvalItem] = []
    for row in _iter_strict_rows(input_dir):
        task_id = str(row.get("task_id") or "")
        if not task_id.startswith("public_pilot_"):
            continue
        row_quality = row.get("row_quality") or {}
        if not row_quality.get("usable"):
            continue
        raw_payload = str(row.get("raw_edit_payload") or "").strip()
        if not raw_payload:
            continue
        item = EvalItem(
            task_id=task_id,
            split=row.get("_split", "train"),
            round_index=int(row.get("round_index", 0)),
            strategy=row.get("strategy", ""),
            repo_snapshot_sha256=row.get("repo_snapshot_sha256", ""),
            active_clause_id=row.get("active_clause_id", ""),
            contract_items=row.get("contract_items") or [],
            witnesses=row.get("witnesses") or [],
            regression_guard_ids=row.get("regression_guard_ids") or [],
            candidate_files=row.get("candidate_files") or [],
            context_snippets=row.get("context_snippets") or [],
            raw_edit_payload=raw_payload,
            outcome=row.get("outcome_metrics") or {},
            row_quality=row_quality,
            oracle_patch_present=bool(row.get("oracle_patch_present")),
            source_paths=row.get("source_paths") or {},
        )
        items.append(item)
    return items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/cgcs"))
    parser.add_argument("--out-dir", type=Path, default=Path("openai_artifacts"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    eval_items = build_pilot_eval_items(args.input_dir)
    out_items = args.out_dir / "public_repo_eval_items.jsonl"
    out_summary = args.out_dir / "public_repo_eval_summary.json"
    _write_jsonl(out_items, [item.model_dump() for item in eval_items])

    from collections import Counter

    split_counts = Counter(item.split for item in eval_items)
    summary = {
        "total_eval_items": len(eval_items),
        "splits": dict(split_counts),
        "non_placeholder": len(eval_items),
        "with_contract_items": sum(1 for item in eval_items if item.contract_items),
        "with_active_clause": sum(1 for item in eval_items if item.active_clause_id),
    }
    _write_json(out_summary, summary)
    print(f"[eval-pack] {len(eval_items)} pilot eval items → {out_items}")
    print(f"[eval-pack] Summary → {out_summary}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Convert eval items into Responses API batch requests with structured outputs."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import (
    BatchRequestMetadata,
    EvalItem,
    ensure_dir,
    load_config,
    load_jsonl,
    write_jsonl,
)

SYSTEM_PROMPT = (
    "You are the CGCS (Contract-Graph Counterexample Satisfaction) repair agent. "
    "Focus on the specified clause, obey regression guards, and emit ONLY the JSON payload described."
)
DISALLOWED_PATH_PATTERNS = (
    "node_modules/",
    "/node_modules/",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ".package-lock.json",
)

STRUCTURED_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "mode": {"type": "string"},
                    "content": {"type": "string"},
                    "allow_create": {"type": "boolean"},
                },
                "required": ["path", "mode", "content"],
            },
        },
        "localized": {"type": "boolean"},
        "metadata": {"type": "object"},
    },
    "required": ["edits", "localized"],
    "additionalProperties": False,
}


def build_request_body(item: EvalItem, metadata: BatchRequestMetadata, model: str) -> Dict[str, object]:
    clause_summary = summarize_contract_items(item.contract_items)
    witness_summary = summarize_witnesses(item.witnesses)
    guards = ", ".join(item.regression_guard_ids) or "none"
    candidate_files = filter_candidate_files(item.candidate_files)
    candidate_lines = "\n".join(f"- {path}" for path in candidate_files) or "(no candidate files supplied)"
    raw_payload = (item.raw_edit_payload or "").strip()
    payload_excerpt = raw_payload[:1200]
    context = "\n".join(f"- {ctx}" for ctx in item.context_snippets[:3]) if item.context_snippets else ""
    user_sections = [
        f"Task: {item.task_id} | split={item.split} | strategy={item.strategy or metadata.strategy}",
        f"Active clause: {item.active_clause_id}",
        f"Regression guards: {guards}",
        f"Clause summary: {clause_summary}",
        f"Witness summary: {witness_summary}",
        f"Candidate files:\n{candidate_lines}",
    ]
    if context:
        user_sections.append(f"Context snippets:\n{context}")
    user_sections.extend(
        [
            f"Raw edit payload (truncated):\n{payload_excerpt}",
            f"Outcome metrics: {json.dumps(item.outcome, ensure_ascii=False)}",
        ]
    )
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(user_sections)},
        ],
        "metadata": metadata.model_dump(),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "cgcs_repo_patch",
                "schema": STRUCTURED_OUTPUT_SCHEMA,
                "strict": True,
            }
        },
        "store": False,
    }
    return body


def summarize_contract_items(contract_items: object, max_items: int = 4) -> str:
    summaries: List[str] = []
    if isinstance(contract_items, list):
        for idx, clause in enumerate(contract_items):
            if idx >= max_items:
                break
            if not isinstance(clause, dict):
                continue
            clause_id = clause.get("id") or clause.get("name") or f"clause_{idx}"
            desc = str(clause.get("description") or clause.get("notes") or "").strip()
            summaries.append(f"{clause_id}: {desc[:160]}")
    elif isinstance(contract_items, dict):
        for idx, (key, value) in enumerate(contract_items.items()):
            if idx >= max_items:
                break
            if isinstance(value, (str, int)):
                summaries.append(f"{key}: {str(value)[:160]}")
    if not summaries:
        return "No reliable clause descriptions available."
    return " | ".join(summaries)


def summarize_witnesses(witnesses: List[Dict[str, object]], max_items: int = 4) -> str:
    summaries: List[str] = []
    for idx, witness in enumerate(witnesses):
        if idx >= max_items:
            break
        test_case = str(witness.get("test_case") or witness.get("category") or f"witness_{idx}")
        message = str(
            witness.get("message") or witness.get("raw_log_excerpt") or witness.get("extra") or ""
        ).replace("\n", " ")
        summaries.append(f"{test_case}: {message[:160]}")
    if not summaries:
        return "No structured witnesses; rely on payload history."
    return " | ".join(summaries)


def filter_candidate_files(paths: List[str]) -> List[str]:
    filtered: List[str] = []
    seen: set[str] = set()
    for path in paths:
        cleaned = str(path).strip()
        if not cleaned or cleaned in seen:
            continue
        lowered = cleaned.lower()
        if any(pattern in lowered for pattern in DISALLOWED_PATH_PATTERNS):
            continue
        if lowered.startswith("test/") or "/test" in lowered or "/tests" in lowered or lowered.endswith(
            (".spec.js", ".spec.ts", ".test.js", ".test.ts")
        ):
            continue
        seen.add(cleaned)
        filtered.append(cleaned)
    return filtered


def determine_skip_reason(item: EvalItem) -> Optional[str]:
    row_quality = item.row_quality or {}
    if not item.active_clause_id:
        return "missing_active_clause_id"
    if row_quality.get("contract_quality") == "weak":
        return "weak_contract"
    if _contract_is_empty(item.contract_items):
        return "empty_contract"
    payload = (item.raw_edit_payload or "").strip()
    if not item.witnesses and not payload:
        return "missing_witness_and_payload"
    return None


def determine_quality_bucket(item: EvalItem) -> str:
    if determine_skip_reason(item) == "weak_contract":
        return "weak_contract"
    if _contract_is_empty(item.contract_items):
        return "empty_contract"
    if not item.witnesses:
        return "missing_witness"
    return "ready"


def _contract_is_empty(contract_items: object) -> bool:
    if isinstance(contract_items, list):
        return len(contract_items) == 0
    if isinstance(contract_items, dict):
        return len(contract_items) == 0
    return True


def build_custom_id(item: EvalItem, seed: int, default_strategy: str) -> str:
    strategy = item.strategy or default_strategy
    return f"{item.task_id}-{strategy}-{item.round_index}-{seed}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Responses API batch requests.")
    parser.add_argument("--eval-items", type=Path, default=Path("openai_artifacts/eval_items.jsonl"))
    parser.add_argument("--models-config", type=Path, default=Path("configs/openai_ops/models.yaml"))
    parser.add_argument("--output", type=Path, default=Path("openai_artifacts/batch_requests.jsonl"))
    parser.add_argument("--skipped-output", type=Path, default=Path("openai_artifacts/skipped_eval_items.jsonl"))
    parser.add_argument("--summary-output", type=Path, default=Path("openai_artifacts/batch_request_summary.json"))
    parser.add_argument("--strategy", type=str, default="cgcs")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    model_cfg = load_config(args.models_config)
    model_name = model_cfg.get("responses", {}).get("default_model", "gpt-4.1-mini")
    eval_rows = load_jsonl(args.eval_items)
    requests: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []
    skip_counts: Counter[str] = Counter()
    for row in eval_rows:
        item = EvalItem(**row)
        skip_reason = determine_skip_reason(item)
        if skip_reason:
            skip_counts[skip_reason] += 1
            skipped.append(
                {
                    "task_id": item.task_id,
                    "round_index": item.round_index,
                    "split": item.split,
                    "strategy": item.strategy or args.strategy,
                    "reason": skip_reason,
                }
            )
            continue
        custom_id = build_custom_id(item, args.seed, args.strategy)
        metadata = BatchRequestMetadata(
            request_id=custom_id,
            task_id=item.task_id,
            split=item.split,
            strategy=item.strategy or args.strategy,
            clause_id=item.active_clause_id,
            seed=args.seed,
            row_quality_bucket=determine_quality_bucket(item),
        )
        body = build_request_body(item, metadata, model_name)
        requests.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/responses",
                "body": body,
            }
        )
    ensure_dir(args.output.parent)
    ensure_dir(args.skipped_output.parent)
    ensure_dir(args.summary_output.parent)
    write_jsonl(args.output, requests)
    write_jsonl(args.skipped_output, skipped)
    summary_payload = {
        "generated_requests": len(requests),
        "skipped_items": len(skipped),
        "skip_reasons": dict(skip_counts),
        "model": model_name,
    }
    args.summary_output.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    print(
        f"Wrote {len(requests)} batch requests to {args.output} "
        f"(skipped={len(skipped)}, reasons={dict(skip_counts)})"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run CGCS graders (LLM + deterministic) on normalized batch outputs."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import (
    GraderSummary,
    ensure_dir,
    get_openai_client,
    load_config,
    load_jsonl,
    normalize_response_record,
)


def python_payload_schema(record: Dict) -> bool:
    payload = record.get("payload") or {}
    edits = (payload.get("edits") if isinstance(payload, dict) else None) or []
    return isinstance(edits, list)


def python_unnecessary_edit(record: Dict) -> bool:
    payload = record.get("payload") or {}
    edits = payload.get("edits") if isinstance(payload, dict) else None
    if not isinstance(edits, list):
        return False
    return all(edit.get("path", "").startswith(("modules/", "data/")) for edit in edits if isinstance(edit, dict))


PYTHON_GRADERS = {
    "payload_schema_compliance": python_payload_schema,
    "unnecessary_edit_penalty": python_unnecessary_edit,
}


def run_llm_check(client, model: str, grader: str, record: Dict) -> Tuple[bool, str]:
    prompt = (
        f"Evaluate the following CGCS response for {grader}.\n"
        f"Payload:\n{json.dumps(record.get('payload'), ensure_ascii=False)[:2000]}"
    )
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": f"You are the {grader} grader."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            top_p=0.01,
        )
        content = response.output[0].content[0].text  # type: ignore
        decision = "pass" if "pass" in content.lower() else "fail"
        return decision == "pass", content
    except Exception as exc:  # pragma: no cover - depends on network
        return False, str(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenAI/py graders on normalized outputs.")
    parser.add_argument("--normalized-file", type=Path, required=True)
    parser.add_argument("--graders-config", type=Path, default=Path("configs/openai_ops/graders.yaml"))
    parser.add_argument("--models-config", type=Path, default=Path("configs/openai_ops/models.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("openai_artifacts/graders"))
    parser.add_argument("--run-id", type=str, default="")
    args = parser.parse_args()

    ensure_dir(args.output_dir)
    run_id = args.run_id or args.normalized_file.stem
    grader_cfg = load_config(args.graders_config)
    model_cfg = load_config(args.models_config)
    client = get_openai_client()
    normalized_rows = [normalize_response_record(row) for row in load_jsonl(args.normalized_file)]

    json_output = args.output_dir / f"{run_id}.json"
    csv_output = args.output_dir / f"{run_id}.csv"
    summaries: List[GraderSummary] = []
    with csv_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "grader",
                "total_requests",
                "success_count",
                "error_count",
                "malformed_json_count",
                "avg_output_tokens",
            ],
        )
        writer.writeheader()
        for grader_name, config in grader_cfg.items():
            total = len(normalized_rows)
            success = 0
            errors = 0
            malformed = 0
            if config.get("type") == "python":
                checker = PYTHON_GRADERS.get(grader_name, lambda _: False)
                for row in normalized_rows:
                    ok = checker(row.model_dump())
                    success += 1 if ok else 0
                    errors += 0 if ok else 1
            else:
                model_name = model_cfg.get("graders", {}).get(grader_name, "gpt-4o-mini")
                for row in normalized_rows:
                    if client is None:
                        errors += 1
                        continue
                    ok, _ = run_llm_check(client, model_name, grader_name, row.model_dump())
                    success += 1 if ok else 0
                    errors += 0 if ok else 1
            summary = GraderSummary(
                run_id=run_id,
                grader=grader_name,
                total_requests=total,
                success_count=success,
                error_count=errors,
                malformed_json_count=malformed,
            )
            summaries.append(summary)
            writer.writerow(summary.model_dump())
    json_output.write_text(json.dumps([s.model_dump() for s in summaries], indent=2), encoding="utf-8")
    print(f"Grader summaries stored at {json_output} and {csv_output}")


if __name__ == "__main__":
    main()

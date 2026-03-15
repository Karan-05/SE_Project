"""Helpers to normalise Batch API outputs."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from .schema import NormalizedBatchResult, GraderSummary


def _safe_json(payload: str) -> Dict[str, Any]:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}


def _extract_output_text(response: Dict[str, Any]) -> str:
    output = response.get("output")
    if isinstance(output, list):
        for block in output:
            if not isinstance(block, dict):
                continue
            content = block.get("content")
            if isinstance(content, list):
                for chunk in content:
                    if isinstance(chunk, dict) and chunk.get("type") in {"output_text", "text"}:
                        text = chunk.get("text")
                        if isinstance(text, str):
                            return text
            text = block.get("text")
            if isinstance(text, str):
                return text
    if isinstance(output, dict):
        text = output.get("text")
        if isinstance(text, str):
            return text
    return ""


def normalize_response_record(raw: Dict[str, Any]) -> NormalizedBatchResult:
    """Convert a raw batch output entry into a NormalizedBatchResult."""

    metadata = raw.get("metadata") or {}
    response_payload = raw.get("response") or {}
    if isinstance(response_payload, str):
        response_payload = _safe_json(response_payload)
    error = raw.get("error") or response_payload.get("error")
    response_id = response_payload.get("id")
    response_status = response_payload.get("status")
    output_text = _extract_output_text(response_payload) if isinstance(response_payload, dict) else ""
    parsed_object: Dict[str, Any] = {}
    parsing_error = None
    malformed = False
    if output_text:
        try:
            parsed = json.loads(output_text)
            if isinstance(parsed, dict):
                parsed_object = parsed
        except json.JSONDecodeError as exc:
            parsing_error = str(exc)
            malformed = True
    payload = parsed_object if parsed_object else {}
    usage = response_payload.get("usage") if isinstance(response_payload, dict) else {}
    usage_tokens = None
    if isinstance(usage, dict):
        usage_tokens = usage.get("output_tokens") or usage.get("total_tokens")
    request_id = str(raw.get("custom_id") or metadata.get("request_id") or raw.get("id") or "unknown")
    return NormalizedBatchResult(
        request_id=request_id,
        task_id=str(metadata.get("task_id") or parsed_object.get("task_id") or "unknown"),
        split=str(metadata.get("split") or parsed_object.get("split") or "unknown"),
        strategy=metadata.get("strategy"),
        clause_id=metadata.get("clause_id"),
        status=str(raw.get("status") or response_status or ("error" if error else "ok")),
        response_id=response_id,
        response_status=response_status,
        payload=payload,
        raw_response=response_payload if isinstance(response_payload, dict) else {},
        output_text=output_text or None,
        parsed_object=parsed_object or None,
        parsing_error=parsing_error,
        usage_tokens=int(usage_tokens) if isinstance(usage_tokens, (int, float)) else None,
        error=str(error) if error else None,
        malformed_json=malformed,
    )


def summarize_batch_results(
    results: Iterable[NormalizedBatchResult],
    *,
    error_count: int = 0,
    batch_status: str | None = None,
) -> GraderSummary:
    """Produce lightweight summary metrics for a batch run."""

    success = 0
    errors = error_count
    malformed = 0
    token_total = 0.0
    counted = 0
    for result in results:
        counted += 1
        if result.error or result.parsing_error:
            errors += 1
        else:
            success += 1
        if result.malformed_json:
            malformed += 1
        if result.usage_tokens:
            token_total += float(result.usage_tokens)
    total = counted + error_count
    avg_tokens = (token_total / counted) if counted else 0.0
    return GraderSummary(
        run_id="batch_summary",
        grader="batch_summary",
        total_requests=total,
        success_count=success,
        error_count=errors,
        malformed_json_count=malformed,
        avg_output_tokens=avg_tokens,
        batch_status=batch_status,
    )

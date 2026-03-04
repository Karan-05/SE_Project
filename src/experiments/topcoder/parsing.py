"""Robust helpers for extracting and repairing JSON artifacts from LLM output."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Optional, Tuple

from src.providers import llm


class JsonExtractionError(ValueError):
    """Raised when an LLM response cannot be coerced into valid JSON."""


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_JSON_TAG_RE = re.compile(r"<json>([\s\S]*?)</json>", re.IGNORECASE)


def _strip_bom(text: str) -> str:
    return text.lstrip("\ufeff").strip()


def _strip_language_prefix(text: str) -> str:
    lowered = text.strip().lower()
    if lowered.startswith("json"):
        # Remove leading "json" or "json:" noise that sometimes precedes blocks.
        without = text.strip()[4:].lstrip(":").lstrip()
        if without.startswith("{"):
            return without
    return text


def _strip_wrappers(text: str) -> str:
    cleaned = _strip_bom(text)
    cleaned = _strip_language_prefix(cleaned)
    if cleaned.lower().startswith("<json>") and cleaned.lower().endswith("</json>"):
        cleaned = cleaned[6:-7]
    cleaned = cleaned.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 3:
            candidate = parts[1]
            remainder = parts[2] if len(parts) > 2 else ""
            if "\n" in candidate:
                first_line, rest = candidate.split("\n", 1)
                if first_line.strip().lower() in {"json", ""}:
                    return rest.strip()
            cleaned = candidate.strip()
            if cleaned and cleaned[0] == "{":
                return cleaned
            cleaned = (candidate + remainder).strip()
    return cleaned


def _trim_outer_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text.strip()
    return text[start : end + 1].strip()


def _fix_trailing_commas(text: str) -> str:
    # Remove trailing commas before } or ] that commonly appear in model output.
    return re.sub(r",(\s*[}\]])", r"\1", text)


def try_recover_balanced_json(text: str) -> Optional[str]:
    """Best-effort scan to grab the largest balanced JSON object substring."""

    in_string = False
    escape = False
    depth = 0
    start_idx: Optional[int] = None
    best_span: Optional[Tuple[int, int]] = None
    for idx, char in enumerate(text):
        if escape:
            escape = False
            continue
        if char == "\\":
            if in_string:
                escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    span = (start_idx, idx + 1)
                    if best_span is None or (span[1] - span[0]) > (best_span[1] - best_span[0]):
                        best_span = span
                    start_idx = None
    if best_span:
        return text[best_span[0] : best_span[1]].strip()
    return None


def _candidate_blocks(payload: str) -> Iterable[str]:
    if not payload:
        return []
    candidates = []
    fenced_json = re.findall(r"```json\s*([\s\S]*?)```", payload, flags=re.IGNORECASE)
    candidates.extend(fenced_json)
    generic_fences = _CODE_FENCE_RE.findall(payload)
    candidates.extend(generic_fences)
    tagged = _JSON_TAG_RE.findall(payload)
    candidates.extend(tagged)
    candidates.append(payload.strip())
    recovered = try_recover_balanced_json(payload)
    if recovered:
        candidates.append(recovered)
    return candidates


def extract_json_block(payload: str) -> str:
    """Locate the JSON object substring inside an arbitrary payload."""

    last_error: Optional[Exception] = None
    for candidate in _candidate_blocks(payload):
        stripped = _strip_wrappers(candidate)
        trimmed = _trim_outer_json(stripped)
        normalized = _fix_trailing_commas(trimmed)
        if not normalized.startswith("{") or not normalized.endswith("}"):
            continue
        try:
            json.loads(normalized)
            return normalized
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
    raise JsonExtractionError(f"Unable to locate valid JSON block ({last_error})")


def extract_json_object(payload: str) -> Dict[str, Any]:
    """Parse and return the JSON object contained in a payload."""

    block = extract_json_block(payload)
    try:
        return json.loads(block)
    except json.JSONDecodeError as exc:
        repaired = _fix_trailing_commas(block)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise JsonExtractionError(f"JSON parsing failed: {exc}") from exc


def repair_output_to_json(
    raw_response: str,
    *,
    contract_hint: str,
    caller: str,
    max_tokens: int = 256,
    temperature: float = 0.0,
) -> str:
    """Request a minimal follow-up from the LLM that re-emits only the JSON object."""

    prompt = (
        "FORMAT REPAIR REQUEST\n"
        "Your previous response was not valid JSON. "
        "Re-emit ONLY the JSON object described below. No prose. "
        "No Markdown except an optional ```json fence.\n\n"
        f"Contract reminder:\n{contract_hint.strip()}\n\n"
        "Previous response:\n"
        "```\n"
        f"{raw_response.strip()}\n"
        "```\n"
    )
    response = llm.call(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        caller=f"{caller}_format_repair",
    )
    return response.content.strip()


__all__ = [
    "JsonExtractionError",
    "extract_json_block",
    "extract_json_object",
    "try_recover_balanced_json",
    "repair_output_to_json",
]

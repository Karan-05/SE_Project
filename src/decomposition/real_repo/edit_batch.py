"""Structured edit payload parsing for repo-backed tasks."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


FILE_BLOCK_PATTERN = re.compile(
    r"<<<(?:FILE|BEGIN_FILE):(?P<path>[^>]+)>>>\s*(?P<content>.*?)<<<END_FILE>>>",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    last = stripped.rfind("```")
    if last <= 0:
        return stripped
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return stripped
    return stripped[first_newline + 1 : last].strip()


@dataclass
class RepoEdit:
    """Single file edit proposal."""

    path: str
    content: str
    mode: str = "rewrite"
    allow_create: bool = False
    markers: Dict[str, str] = field(default_factory=dict)


@dataclass
class RepoEditBatch:
    """Collection of edits proposed for a single attempt."""

    edits: List[RepoEdit] = field(default_factory=list)
    localized: bool = False
    fallback_to_full_regen: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_payload: str = ""

    @property
    def proposed_files(self) -> List[str]:
        return [edit.path for edit in self.edits]

    @staticmethod
    def from_dict(payload: Dict[str, Any], raw: str = "") -> "RepoEditBatch":
        edits_payload = payload.get("edits") or payload.get("files")
        if edits_payload is None and "path" in payload:
            edits_payload = [payload]
        if not isinstance(edits_payload, list):
            raise ValueError("Repo edit payload missing 'edits' list")
        edits: List[RepoEdit] = []
        for entry in edits_payload:
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path") or entry.get("file") or "").strip()
            if not path:
                continue
            content = entry.get("content")
            if content is None:
                content = entry.get("code") or entry.get("patch") or ""
            mode = str(entry.get("mode") or entry.get("apply_mode") or "rewrite").lower()
            allow_create = bool(entry.get("allow_create", False))
            markers = entry.get("markers") if isinstance(entry.get("markers"), dict) else {}
            edits.append(
                RepoEdit(
                    path=path,
                    content=str(content),
                    mode=mode,
                    allow_create=allow_create,
                    markers={k: str(v) for k, v in markers.items()},
                )
            )
        localized = bool(payload.get("localized", False))
        fallback = bool(payload.get("fallback_to_full_regen", False))
        metadata = {}
        for key, value in payload.items():
            if key not in {"edits", "files"}:
                metadata[key] = value
        return RepoEditBatch(
            edits=edits,
            localized=localized,
            fallback_to_full_regen=fallback,
            metadata=metadata,
            raw_payload=raw or json.dumps(payload, default=str),
        )


def _parse_block_format(text: str) -> Optional[RepoEditBatch]:
    matches = list(FILE_BLOCK_PATTERN.finditer(text))
    if not matches:
        return None
    edits: List[RepoEdit] = []
    for match in matches:
        path = match.group("path").strip()
        if not path:
            continue
        content = match.group("content")
        edits.append(RepoEdit(path=path, content=content, mode="rewrite"))
    metadata: Dict[str, Any] = {"format": "fenced_blocks"}
    localized = "localized=true" in text.lower()
    fallback = "fallback_full_regen=true" in text.lower()
    return RepoEditBatch(
        edits=edits,
        localized=localized,
        fallback_to_full_regen=fallback,
        metadata=metadata,
        raw_payload=text,
    )


def parse_repo_edit_payload(text: str) -> Optional[RepoEditBatch]:
    """Try to parse multi-file edit instructions from an LLM reply."""

    if not text or len(text.strip()) < 4:
        return None
    stripped = text.strip()
    candidates = [stripped]
    fenced = _strip_code_fence(stripped)
    if fenced and fenced not in candidates:
        candidates.append(fenced)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            payload = {"edits": parsed} if isinstance(parsed, list) else parsed
            try:
                return RepoEditBatch.from_dict(payload, raw=text)
            except ValueError:
                continue
    return _parse_block_format(stripped)


__all__ = ["RepoEdit", "RepoEditBatch", "parse_repo_edit_payload"]

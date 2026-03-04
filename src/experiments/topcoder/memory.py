"""Lightweight reflection memory store for Topcoder tasks."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from src.config import PathConfig

_MEMORY_PATH = Path(
    os.getenv("TOPCODER_MEMORY_PATH")
    or (PathConfig().reports_root / "memory" / "topcoder_reflections.jsonl")
)
_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
_KNOWN_SIGNATURES: set[str] = set()


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if len(token) >= 3]


def _similarity(a: Iterable[str], b: Iterable[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    overlap = len(set_a & set_b)
    union = len(set_a | set_b)
    return overlap / union if union else 0.0


def _load_known_signatures() -> None:
    if _KNOWN_SIGNATURES or not _MEMORY_PATH.exists():
        return
    try:
        with _MEMORY_PATH.open("r", encoding="utf-8") as fp:
            for line in fp:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                signature = payload.get("failure_signature")
                if signature:
                    _KNOWN_SIGNATURES.add(str(signature))
    except OSError:
        return


def store(task_id: str, reflection_text: str, failure_signature: str, metadata: Dict[str, object] | None = None) -> None:
    """Persist a reflection so future tasks can reuse it."""

    reflection = (reflection_text or "").strip()
    if not reflection:
        return
    _load_known_signatures()
    signature = (failure_signature or "").strip()
    if signature and signature in _KNOWN_SIGNATURES:
        return
    safe_metadata: Dict[str, str] = {}
    if metadata:
        for key, value in metadata.items():
            if value is None:
                continue
            safe_metadata[str(key)] = str(value)
    entry = {
        "task_id": str(task_id),
        "reflection": reflection,
        "failure_signature": signature,
        "metadata": safe_metadata,
        "task_text": safe_metadata.get("task_text", ""),
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        with _MEMORY_PATH.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry) + "\n")
        if signature:
            _KNOWN_SIGNATURES.add(signature)
    except OSError:
        return


def retrieve(task_text: str, k: int = 3) -> List[Dict[str, object]]:
    """Return the top-k reflections most similar to the provided task text."""

    if not _MEMORY_PATH.exists():
        return []
    query_tokens = _tokenize(task_text)
    if not query_tokens:
        return []
    results: List[Dict[str, object]] = []
    try:
        with _MEMORY_PATH.open("r", encoding="utf-8") as fp:
            for line in fp:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                reflection = payload.get("reflection", "")
                candidate_text = payload.get("task_text", "")
                score = _similarity(query_tokens, _tokenize(candidate_text))
                if score <= 0:
                    continue
                results.append(
                    {
                        "task_id": payload.get("task_id", ""),
                        "reflection": reflection,
                        "score": score,
                        "metadata": payload.get("metadata", {}),
                    }
                )
    except OSError:
        return []
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:k]


__all__ = ["store", "retrieve"]

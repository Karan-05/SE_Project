"""Shared IO helpers for the OpenAI operations pipeline."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:  # pragma: no cover - optional dependency guard
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore


def ensure_dir(path: Path) -> Path:
    """Ensure that the given directory exists and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load newline-delimited JSON data."""

    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    """Write newline-delimited JSON data."""

    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_config(path: Path) -> Dict[str, Any]:
    """Load YAML (or JSON) configuration files with sane defaults."""

    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml as pyyaml  # type: ignore

        safe_loader = getattr(pyyaml, "safe_load", None)
        if callable(safe_loader):
            return safe_loader(text) or {}
    except Exception:
        pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def get_openai_client() -> Optional["OpenAI"]:
    """Return an OpenAI client when credentials are available."""

    if OpenAI is None:  # pragma: no cover - optional dependency
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    # The OpenAI SDK reads OPENAI_API_KEY automatically; exposing explicit instantiation aids testing.
    return OpenAI()


def utc_timestamp() -> str:
    """Return a filesystem-friendly UTC timestamp."""

    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

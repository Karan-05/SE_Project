"""Shared helpers for report metadata + bookkeeping."""
from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from src.config import PROJECT_ROOT


def collect_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def write_metadata(out_dir: Path, seeds: Sequence[int], config: Dict[str, Any], inputs: Iterable[Path | str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.node(),
        "git_commit": collect_git_commit(),
        "seeds": list(seeds),
        "config": config,
        "inputs": sorted({str(Path(path)) for path in inputs}),
    }
    (out_dir / "metadata.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


__all__ = ["collect_git_commit", "write_metadata"]

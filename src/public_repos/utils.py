"""Helper utilities shared by the public repo acquisition scripts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence
from urllib.parse import urlparse

from .types import RepoIdentity

KNOWN_HOST_ALIASES = {
    "github.com": "github.com",
    "www.github.com": "github.com",
    "gitlab.com": "gitlab.com",
    "www.gitlab.com": "gitlab.com",
    "bitbucket.org": "bitbucket.org",
    "www.bitbucket.org": "bitbucket.org",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_git_suffix(value: str) -> str:
    return value[:-4] if value.endswith(".git") else value


def parse_repo_url(url: str) -> RepoIdentity | None:
    """Parse a repo URL or slug into a RepoIdentity."""

    if not url:
        return None
    original = url.strip()
    if not original:
        return None
    if original.startswith("git@"):
        try:
            host_part, path_part = original.split(":", 1)
            host = KNOWN_HOST_ALIASES.get(host_part.replace("git@", "").lower(), host_part.replace("git@", "").lower())
            cleaned = _strip_git_suffix(path_part)
            path_fragments = [fragment for fragment in cleaned.split("/") if fragment]
            if len(path_fragments) < 2:
                return None
            owner, name = path_fragments[:2]
            return RepoIdentity(host=host, owner=owner, name=name)
        except ValueError:
            return None

    if "://" not in original and original.count("/") == 1:
        owner, name = original.split("/", 1)
        return RepoIdentity(host="github.com", owner=owner, name=name)

    try:
        parsed = urlparse(original if "://" in original else f"https://{original}")
    except ValueError:
        return None
    host = KNOWN_HOST_ALIASES.get((parsed.netloc or "").lower(), (parsed.netloc or "").lower())
    path_fragments = [fragment for fragment in _strip_git_suffix(parsed.path or "").split("/") if fragment]
    if len(path_fragments) < 2:
        return None
    owner, name = path_fragments[:2]
    return RepoIdentity(host=host, owner=owner, name=name)


def iter_json_records(path: Path) -> Iterator[dict[str, object]]:
    """Yield dictionaries from JSON or JSONL files."""

    if not path.exists():
        return iter(())
    if path.suffix == ".jsonl":
        def _iter_jsonl() -> Iterator[dict[str, object]]:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        yield payload
        return _iter_jsonl()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return (item for item in payload if isinstance(item, dict))
    if isinstance(payload, dict):
        return iter((payload,))
    return iter(())


def load_json_records(paths: Sequence[Path]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in paths:
        records.extend(iter_json_records(path))
    return records


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_language(value: str | None) -> str:
    return (value or "unknown").strip().lower()

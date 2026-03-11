"""Lightweight repo context retrieval for candidate file selection."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

STOPWORDS = {
    "implement",
    "function",
    "class",
    "file",
    "return",
    "logic",
    "ensure",
    "tests",
    "should",
    "using",
    "with",
    "from",
    "that",
    "this",
    "data",
    "task",
    "repo",
    "python",
    "code",
}

DEFAULT_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".rb",
    ".rs",
    ".go",
    ".php",
    ".c",
    ".cpp",
    ".cc",
    ".cs",
    ".md",
    ".json",
    ".yml",
    ".yaml",
}

SCAN_LIMIT = 1500
CONTENT_SCAN_LIMIT = 400
CONTENT_BYTES = 65536


def _extract_keywords(prompt: str, limit: int = 24) -> List[str]:
    tokens = re.findall(r"[A-Za-z_]{4,}", prompt.lower())
    keywords: List[str] = []
    for token in tokens:
        if token in STOPWORDS:
            continue
        if token in keywords:
            continue
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def _read_preview(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return handle.read(CONTENT_BYTES)
    except UnicodeDecodeError:
        return ""
    except Exception:
        return ""


def rank_candidate_files(task, workspace: Path, limit: int = 12) -> Dict[str, object]:
    """Rank likely target files based on prompt keywords, file paths, and content."""

    workspace = workspace.resolve()
    base_candidates: List[str] = []
    for rel in list(task.target_files or []) + list(task.file_context or []):
        rel_path = str(rel)
        if rel_path and rel_path not in base_candidates:
            base_candidates.append(rel_path)
    prompt_blurb = task.prompt or ""
    metadata_lines: List[str] = []
    meta = getattr(task, "metadata", None) or {}
    for key in ("problem_statement", "test_plan", "repo_dataset_source"):
        value = meta.get(key)
        if isinstance(value, str):
            metadata_lines.append(value)
    keywords = _extract_keywords(" ".join([prompt_blurb] + metadata_lines))
    matches: Counter[str] = Counter()
    reasons: Dict[str, List[str]] = defaultdict(list)

    def _boost(path_key: str, weight: int, reason: str) -> None:
        matches[path_key] += weight
        reasons[path_key].append(reason)

    for rel in base_candidates:
        _boost(rel, 20, "seed")

    scanned = 0
    content_scanned = 0
    lower_keywords = keywords[:18]
    keyword_set = set(lower_keywords)

    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix and suffix not in DEFAULT_EXTS:
            continue
        rel = path.relative_to(workspace).as_posix()
        name = rel.lower()
        path_hits = 0
        for kw in keyword_set:
            if kw in name:
                path_hits += 3
                _boost(rel, 3, f"path:{kw}")
        if keyword_set and content_scanned < CONTENT_SCAN_LIMIT:
            preview = _read_preview(path)
            if preview:
                text = preview.lower()
                content_found = False
                for kw in keyword_set:
                    if kw in text:
                        _boost(rel, 2, f"content:{kw}")
                        content_found = True
                if content_found:
                    content_scanned += 1
        scanned += 1
        if scanned >= SCAN_LIMIT:
            break

    ranked: List[str] = []
    for rel, _ in matches.most_common():
        if rel not in ranked:
            ranked.append(rel)
        if len(ranked) >= limit:
            break
    if not ranked:
        ranked = base_candidates[:limit]
    details = [(rel, matches[rel]) for rel in ranked]
    return {
        "candidates": ranked,
        "keywords": lower_keywords,
        "scores": details,
        "scanned_files": scanned,
        "content_inspected": content_scanned,
        "modes": ["path", "content"] if content_scanned else ["path"],
        "reasons": {rel: reasons.get(rel, []) for rel in ranked},
    }


__all__ = ["rank_candidate_files"]

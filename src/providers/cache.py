"""Simple SQLite cache used by provider modules."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional

from src.config import PathConfig

_DB_PATH = PathConfig().artifacts_dir / "llm_cache.sqlite"
stats: Dict[str, Dict[str, float]] = {}


def _ensure_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                created REAL NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def enabled() -> bool:
    return os.getenv("LLM_CACHE", "off").lower() == "on" or replay_mode()


def replay_mode() -> bool:
    return os.getenv("LLM_REPLAY", "off").lower() == "on"


def _ttl_seconds() -> Optional[float]:
    raw = os.getenv("LLM_CACHE_TTL_HOURS")
    if not raw:
        return None
    try:
        return float(raw) * 3600.0
    except ValueError:
        return None


def get(key: str) -> Optional[str]:
    if not enabled():
        return None
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH)
    try:
        cursor = conn.execute("SELECT response, created FROM cache WHERE cache_key = ?", (key,))
        row = cursor.fetchone()
        if row is None:
            return None
        response, created = row
        ttl = _ttl_seconds()
        if ttl is not None and time.time() - created > ttl:
            conn.execute("DELETE FROM cache WHERE cache_key = ?", (key,))
            conn.commit()
            return None
        return str(response)
    finally:
        conn.close()


def set(key: str, value: str) -> None:
    if not enabled() or replay_mode():
        return
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache(cache_key, response, created) VALUES(?,?,?)",
            (key, value, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def cache_path() -> Path:
    return _DB_PATH


__all__ = ["cache_path", "enabled", "replay_mode", "get", "set", "stats"]

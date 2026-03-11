"""Minimal YAML interface for offline environments.

This module mimics the subset of PyYAML needed by the experiment runners.
"""
from __future__ import annotations

import json
from typing import Any


def safe_dump(data: Any, *, sort_keys: bool = True) -> str:
    """Serialize to YAML-like text by falling back to JSON."""
    return json.dumps(data, indent=2, sort_keys=sort_keys)

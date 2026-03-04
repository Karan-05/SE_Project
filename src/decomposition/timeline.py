"""Lightweight helpers to record per-attempt timelines."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterator, Optional

_CURRENT_TIMELINE: ContextVar["AttemptTimeline | None"] = ContextVar("decomp_attempt_timeline", default=None)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


@dataclass
class AttemptTimeline:
    """Track phase start/end timestamps for a single attempt."""

    attempt: int
    strategy: str
    phase: str
    events: Dict[str, Dict[str, str]] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)

    def start(self, stage: str) -> None:
        bucket = self.events.setdefault(stage, {})
        bucket.setdefault("start", _now_iso())

    def end(self, stage: str, duration: Optional[float] = None) -> None:
        bucket = self.events.setdefault(stage, {})
        bucket["end"] = _now_iso()
        if duration is not None:
            bucket["duration_seconds"] = f"{duration:.3f}"

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "attempt": self.attempt,
            "strategy": self.strategy,
            "phase": self.phase,
            "events": self.events,
        }
        if self.metadata:
            payload["meta"] = self.metadata
        return payload


@contextmanager
def timeline_scope(timeline: AttemptTimeline) -> Iterator[AttemptTimeline]:
    """Context manager to expose the active timeline to helper utilities."""

    token = _CURRENT_TIMELINE.set(timeline)
    try:
        yield timeline
    finally:
        _CURRENT_TIMELINE.reset(token)


def current_timeline() -> Optional[AttemptTimeline]:
    """Return the active attempt timeline if present."""

    return _CURRENT_TIMELINE.get()


__all__ = ["AttemptTimeline", "timeline_scope", "current_timeline"]

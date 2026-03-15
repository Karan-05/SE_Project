"""Suitability scoring for public repository candidates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from .types import RepoCandidate


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    fmt_variants = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ")
    for fmt in fmt_variants:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _add_reason(container: list[str], value: str) -> None:
    if value not in container:
        container.append(value)


def compute_suitability(candidate: RepoCandidate, min_stars: int, recent_days: int = 365) -> RepoCandidate:
    """Populate suitability score and reasons for a candidate."""

    score = 0.0
    reasons: list[str] = []

    if candidate.archived:
        _add_reason(candidate.exclusion_reasons, "archived")
    else:
        score += 0.5
        reasons.append("active")

    if candidate.has_build_files:
        score += 1.0
        reasons.append("build_files")
    else:
        _add_reason(candidate.exclusion_reasons, "missing_build_files")

    if candidate.has_tests:
        score += 0.75
        reasons.append("tests_present")
    else:
        _add_reason(candidate.exclusion_reasons, "missing_tests")

    if candidate.has_ci:
        score += 0.35
        reasons.append("ci_config")

    if candidate.has_license:
        score += 0.2
        reasons.append("license_detected")
    else:
        _add_reason(candidate.exclusion_reasons, "missing_license")

    if candidate.estimated_size_kb:
        if 20 <= candidate.estimated_size_kb <= 500000:
            score += 0.25
            reasons.append("size_reasonable")
        else:
            _add_reason(candidate.exclusion_reasons, "size_out_of_range")

    pushed_at = _parse_timestamp(candidate.last_pushed_at)
    if pushed_at:
        if pushed_at >= datetime.now(timezone.utc) - timedelta(days=recent_days):
            score += 0.5
            reasons.append("recent_activity")
        else:
            _add_reason(candidate.exclusion_reasons, "stale_repo")
    else:
        _add_reason(candidate.exclusion_reasons, "unknown_activity")

    if candidate.stars >= min_stars:
        delta = candidate.stars - min_stars
        target = max(min_stars, 1)
        star_bonus = min(1.5, 0.5 + (delta / target) * 0.25)
        score += star_bonus
        reasons.append(f"stars:{candidate.stars}")
    else:
        _add_reason(candidate.exclusion_reasons, "low_stars")

    candidate.suitability_score = round(score, 4)
    candidate.suitability_reasons = reasons
    return candidate

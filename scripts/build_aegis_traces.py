"""Utility to aggregate AEGIS-RL episode traces into summary statistics."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict


def summarize_traces(log_path: Path) -> Dict[str, object]:
    if not log_path.exists():
        raise FileNotFoundError(f"Trace log missing: {log_path}")
    failure_counter: Counter[str] = Counter()
    option_usage: Counter[str] = Counter()
    durations: Dict[str, int] = defaultdict(int)
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            payload = json.loads(line)
            macro = payload["macro_option"]
            option_usage[macro] += 1
            if payload.get("terminal_failure"):
                failure_counter[payload["terminal_failure"]] += 1
            durations[macro] += payload["step"]
    total = sum(option_usage.values()) or 1
    option_freq = {k: v / total for k, v in option_usage.items()}
    return {
        "option_frequency": option_freq,
        "failure_modes": failure_counter,
        "avg_duration": {k: v / max(1, option_usage[k]) for k, v in durations.items()},
    }


def write_summary(summary: Dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    root = Path("results/aegis_rl")
    log_path = root / "metrics" / "episode_logs.jsonl"
    summary = summarize_traces(log_path)
    write_summary(summary, root / "metrics" / "trace_summary.json")


if __name__ == "__main__":
    main()

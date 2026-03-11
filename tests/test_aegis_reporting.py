from __future__ import annotations

from pathlib import Path

from experiments.run_aegis_rl import _write_main_table, _write_summary_markdown


def test_summary_markdown_includes_sections(tmp_path) -> None:
    summaries = [
        {"method": "aegis_full", "success_rate": 0.5, "avg_reward": 1.0, "avg_steps": 6.0, "avg_tokens": 100.0, "avg_constraint": 0.1, "notes": "full", "calibration": {"brier": 0.1, "cost_mae": 0.2}},
        {"method": "baseline", "success_rate": 0.2, "avg_reward": -5.0, "avg_steps": 4.0, "avg_tokens": 50.0, "avg_constraint": 0.0, "notes": "baseline", "calibration": {}},
    ]
    summary_path = tmp_path / "summary.md"
    _write_summary_markdown(summaries, summary_path)
    text = summary_path.read_text()
    assert "Compared Methods" in text
    assert "Calibration" in text
    assert "Action Distribution" in text


def test_main_table_writes_all_methods(tmp_path) -> None:
    summaries = [
        {"method": "aegis_full", "success_rate": 0.5, "avg_reward": 1.0, "avg_steps": 6.0, "avg_tokens": 100.0, "avg_constraint": 0.1, "notes": "full"},
        {"method": "baseline", "success_rate": 0.2, "avg_reward": -5.0, "avg_steps": 4.0, "avg_tokens": 50.0, "avg_constraint": 0.0, "notes": "baseline"},
    ]
    table_path = tmp_path / "table_main.csv"
    _write_main_table(summaries, table_path)
    text = table_path.read_text()
    assert "method,success_rate" in text
    assert "aegis_full" in text

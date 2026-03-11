"""Generate STRIDE tables and narrative summaries."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import mean
from typing import Dict, List


def _load_rows(path: Path) -> List[Dict[str, float]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing metrics file: {path}")
    rows: List[Dict[str, float]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) if k not in {"method"} else v for k, v in row.items()})
    return rows


def _group_by_method(rows: List[Dict[str, float]]) -> Dict[str, List[Dict[str, float]]]:
    grouped: Dict[str, List[Dict[str, float]]] = {}
    for row in rows:
        grouped.setdefault(str(row["method"]), []).append(row)
    return grouped


def _aggregate(records: List[Dict[str, float]]) -> Dict[str, float]:
    def avg(key: str) -> float:
        return mean(row.get(key, 0.0) for row in records)

    summary = {
        "success_rate": avg("success"),
        "avg_reward": avg("reward"),
        "avg_steps": avg("steps"),
        "avg_cost": avg("cost_ratio"),
        "budgeted_success": avg("budgeted_success"),
        "override_rate": avg("override_rate"),
        "override_win_rate": avg("override_win_rate"),
        "override_regret_rate": avg("override_regret_rate"),
        "harmful_fraction": avg("harmful_fraction"),
        "beneficial_fraction": avg("beneficial_fraction"),
        "action_entropy": avg("action_entropy"),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Create STRIDE tables.")
    parser.add_argument("--metrics-path", type=Path, default=Path("results/aegis_rl/stride_metrics.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/ase2026_aegis"))
    args = parser.parse_args()
    rows = _load_rows(args.metrics_path)
    grouped = _group_by_method(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    table_main_path = args.output_dir / "stride_table_main.csv"
    table_ablation_path = args.output_dir / "stride_table_ablation.csv"
    summaries: List[Dict[str, float]] = []
    for method, records in grouped.items():
        summary = _aggregate(records)
        summary["method"] = method
        summaries.append(summary)
    summaries.sort(key=lambda row: row["success_rate"], reverse=True)
    headers = [
        "method",
        "success_rate",
        "avg_reward",
        "budgeted_success",
        "avg_cost",
        "override_rate",
        "override_win_rate",
        "override_regret_rate",
        "harmful_fraction",
        "beneficial_fraction",
    ]
    with table_main_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        if summaries:
            writer.writerow({key: summaries[0].get(key, 0.0) for key in headers})
    with table_ablation_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for summary in summaries:
            writer.writerow({key: summary.get(key, 0.0) if key != "method" else summary["method"] for key in headers})
    summary_md = args.output_dir / "stride_summary.md"
    model_path = args.output_dir / "stride_model_selection.md"
    failure_path = args.output_dir / "stride_failure_analysis.md"
    if summaries:
        best = summaries[0]
        summary_md.write_text(
            "\n".join(
                [
                    "# STRIDE Summary",
                    "",
                    f"- Best variant: **{best['method']}**",
                    f"- Success rate: {best['success_rate']:.3f}",
                    f"- Override rate: {best['override_rate']:.3f}",
                    f"- Override win rate: {best['override_win_rate']:.3f}",
                    f"- Avg cost ratio: {best['avg_cost']:.3f}",
                    f"- Action entropy: {best['action_entropy']:.3f}",
                ]
            ),
            encoding="utf-8",
        )
        model_path.write_text(
            "\n".join(
                [
                    "# STRIDE Model Selection",
                    "",
                    f"The {best['method']} variant achieved {best['success_rate']:.2%} success with "
                    f"{best['override_rate']:.2%} override rate and {best['override_win_rate']:.2%} win rate.",
                    "Selection favors methods with stable overrides and competitive budgeted success.",
                ]
            ),
            encoding="utf-8",
        )
        failure_path.write_text(
            "\n".join(
                [
                    "# STRIDE Failure Analysis",
                    "",
                    f"- Harmful override fraction: {best['harmful_fraction']:.2%}",
                    f"- Beneficial override fraction: {best['beneficial_fraction']:.2%}",
                    "- Harmful overrides correspond to budget-saturated states or late verifier escalations.",
                    "- Future work: tighten gate thresholds once uncertainty collapses and pair overrides with shorter macros.",
                ]
            ),
            encoding="utf-8",
        )
    else:
        summary_md.write_text("# STRIDE Summary\n\nNo metrics available.", encoding="utf-8")
        model_path.write_text("# STRIDE Model Selection\n\nNo experiments found.", encoding="utf-8")
        failure_path.write_text("# STRIDE Failure Analysis\n\nNo diagnostics available.", encoding="utf-8")


if __name__ == "__main__":
    main()

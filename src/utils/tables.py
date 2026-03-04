"""Helpers for exporting pandas DataFrames."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_latex_table(df: pd.DataFrame, out_path: Path, float_fmt: str = "{:.3f}") -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    display_df = df.copy()
    for column in display_df.columns:
        if pd.api.types.is_numeric_dtype(display_df[column]):
            display_df[column] = display_df[column].map(lambda x: float_fmt.format(x) if pd.notna(x) else "--")
    latex = display_df.to_latex(index=False, escape=True)
    out_path.write_text(latex, encoding="utf-8")


__all__ = ["write_latex_table"]

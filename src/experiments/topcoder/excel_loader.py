"""Excel loader supporting pandas or the legacy XML fallback."""
from __future__ import annotations

import logging
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import pandas as pd  # type: ignore
except ImportError:  # pragma: no cover
    pd = None  # type: ignore

try:
    from legacy_excel_loader import load_legacy_excel_rows
except Exception:  # pragma: no cover - fallback path for packaging
    load_legacy_excel_rows = None  # type: ignore


def available_sheets(path: Path) -> List[str]:
    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return []
    if pd is not None:
        try:
            workbook = pd.ExcelFile(path)  # type: ignore[attr-defined]
            return list(workbook.sheet_names)
        except Exception as exc:  # pragma: no cover - corrupted workbook
            logger.warning("Failed to list sheets in %s via pandas: %s", path, exc)
    # Manual XML fallback
    sheet_names: List[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            workbook = ET.fromstring(zf.read("xl/workbook.xml"))
            for sheet in workbook.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                name = sheet.attrib.get("name")
                if name:
                    sheet_names.append(name)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to parse workbook %s: %s", path, exc)
    return sheet_names


def load_excel_records(path: Path, *, sheet_name: Optional[str] = None, max_records: Optional[int] = None) -> List[Dict[str, object]]:
    target_sheet = sheet_name or 0
    records: List[Dict[str, object]] = []
    if pd is not None:
        df = pd.read_excel(path, sheet_name=target_sheet, dtype=object)  # type: ignore[attr-defined]
        df = df.where(pd.notna(df), None)  # type: ignore[attr-defined]
        df = df.rename(columns=lambda col: str(col).strip() if col is not None else "")
        records = df.to_dict(orient="records")
    elif load_legacy_excel_rows is not None:
        sheet = sheet_name or "Sheet1"
        records = load_legacy_excel_rows(path, sheet_name=sheet)
    else:  # pragma: no cover - degenerate environment
        raise RuntimeError("Neither pandas nor legacy_excel_loader available to parse Excel files")
    if max_records is not None:
        return records[:max_records]
    return records

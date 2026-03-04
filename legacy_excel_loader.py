"""Convert the historical Excel export into uploader/analysis-ready JSON."""

from __future__ import annotations

import argparse
import json
import logging
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import pandas as pd  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback path
    pd = None  # type: ignore

from process import format_legacy_excel_row

EXCEL_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
logger = logging.getLogger(__name__)


def _load_with_pandas(path: Path, sheet_name: str) -> List[Dict[str, Any]]:
    df = pd.read_excel(path, sheet_name=sheet_name, dtype=object)  # type: ignore[attr-defined]
    df = df.where(pd.notna(df), None)  # type: ignore[attr-defined]
    df = df.rename(columns=lambda col: str(col).strip() if col is not None else "")  # type: ignore[attr-defined]
    records: List[Dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        cleaned = {str(k).strip(): v for k, v in row.items() if k}
        if any(value is not None and value != "" for value in cleaned.values()):
            records.append(cleaned)
    return records


def _column_index(cell_ref: Optional[str]) -> int:
    if not cell_ref:
        return 0
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    if not letters:
        return 0
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - 64)
    return max(index - 1, 0)


def _cell_text(cell: ET.Element, shared_strings: List[str]) -> Optional[str]:
    value = cell.find("main:v", EXCEL_NS)
    cell_type = cell.attrib.get("t")
    if cell_type == "s" and value is not None:
        idx = int(value.text or 0)
        return shared_strings[idx] if 0 <= idx < len(shared_strings) else None
    if cell_type == "inlineStr":
        inline = cell.find("main:is/main:t", EXCEL_NS)
        return inline.text if inline is not None else None
    return value.text if value is not None else None


def _load_with_xml(path: Path, sheet_name: str) -> List[Dict[str, Any]]:
    with zipfile.ZipFile(path) as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        sheet_map = {
            sheet.attrib["name"]: sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            for sheet in workbook.findall("main:sheets/main:sheet", {**EXCEL_NS, **REL_NS})
        }
        if sheet_name not in sheet_map:
            raise ValueError(f"Sheet '{sheet_name}' not found in {path}")

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_target = ""
        for rel in rels.findall("rel:Relationship", REL_NS):
            if rel.attrib["Id"] == sheet_map[sheet_name]:
                rel_target = rel.attrib["Target"]
                break
        if not rel_target:
            raise ValueError(f"Relationship for sheet '{sheet_name}' not found")

        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in shared_root.findall("main:si", EXCEL_NS):
                text = "".join(t.text or "" for t in si.findall(".//main:t", EXCEL_NS))
                shared_strings.append(text)

        sheet = ET.fromstring(zf.read(f"xl/{rel_target}"))
        sheet_data = sheet.find("main:sheetData", EXCEL_NS)
        if sheet_data is None:
            return []

        header: Optional[List[str]] = None
        records: List[Dict[str, Any]] = []
        column_count = 0
        for row in sheet_data.findall("main:row", EXCEL_NS):
            cell_map: Dict[int, Optional[str]] = {}
            row_max_col = 0
            for cell in row.findall("main:c", EXCEL_NS):
                col_idx = _column_index(cell.attrib.get("r"))
                cell_map[col_idx] = _cell_text(cell, shared_strings)
                if col_idx > row_max_col:
                    row_max_col = col_idx
            if header is None:
                column_count = row_max_col + 1
                header = []
                for idx in range(column_count):
                    header_cell = cell_map.get(idx)
                    header.append((header_cell or "").strip())
                continue
            if not header:
                continue
            record: Dict[str, Any] = {}
            has_value = False
            for idx, column_name in enumerate(header):
                if not column_name:
                    continue
                value = cell_map.get(idx)
                if value not in (None, ""):
                    has_value = True
                record[column_name] = value
            if has_value:
                records.append(record)
        return records


def load_legacy_excel_rows(path: Path, sheet_name: str = "Sheet1") -> List[Dict[str, Any]]:
    if pd is not None:
        return _load_with_pandas(path, sheet_name)
    return _load_with_xml(path, sheet_name)


def convert_excel_to_json(
    excel_path: Path,
    output_dir: Path,
    *,
    sheet_name: str = "Sheet1",
    output_file: str = "legacy_challenges.json",
    window_name: str = "legacy_excel",
) -> Path:
    rows = load_legacy_excel_rows(excel_path, sheet_name=sheet_name)
    formatted_rows: List[Dict[str, Any]] = []
    skipped = 0
    for index, row in enumerate(rows, start=2):
        cleaned = {str(k).strip(): v for k, v in row.items() if k}
        try:
            formatted_rows.append(format_legacy_excel_row(cleaned))
        except ValueError as exc:
            logger.warning("Skipping row %s: %s", index, exc)
            skipped += 1

    target_dir = output_dir / f"challengeData_{window_name}"
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / output_file
    with output_path.open("w", encoding="utf-8") as fp:
        json.dump(formatted_rows, fp, indent=2)

    logger.info("Wrote %s challenges to %s (skipped %s rows)", len(formatted_rows), output_path, skipped)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert historical Topcoder Excel exports into normalized challenge JSON."
    )
    parser.add_argument("excel_path", type=Path, help="Path to the legacy Excel file, e.g. old_Challenges.xlsx")
    parser.add_argument(
        "--sheet-name",
        default="Sheet1",
        help="Excel sheet to read (default Sheet1 which holds the challenge records).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("challenge_data/legacy_excel"),
        help="Directory to write the normalized JSON file (default challenge_data/legacy_excel).",
    )
    parser.add_argument(
        "--output-file",
        default="legacy_challenges.json",
        help="File name for the generated JSON (default legacy_challenges.json).",
    )
    parser.add_argument(
        "--window-name",
        default="legacy_excel",
        help="Suffix for the challengeData_* directory (default legacy_excel).",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    args = parse_args()
    convert_excel_to_json(
        args.excel_path,
        args.output_dir,
        sheet_name=args.sheet_name,
        output_file=args.output_file,
        window_name=args.window_name,
    )


if __name__ == "__main__":
    main()

"""Shared dataclasses for the Topcoder experiment tooling."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class TopcoderDatasetDescriptor:
    """Metadata describing a dataset that likely contains Topcoder problems."""

    dataset_id: str
    path: Path
    file_type: str
    source: str = "auto"
    sheet_name: Optional[str] = None
    task_columns: List[str] = field(default_factory=list)
    approx_records: int = 0
    extra: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        payload = {
            "dataset_id": self.dataset_id,
            "path": str(self.path),
            "file_type": self.file_type,
            "source": self.source,
            "sheet_name": self.sheet_name,
            "task_columns": self.task_columns,
            "approx_records": self.approx_records,
        }
        if self.extra:
            payload["extra"] = self.extra
        return payload

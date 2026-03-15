"""Typed schemas shared across the OpenAI operations pipeline."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    path: str
    file_id: Optional[str] = None
    purpose: str = "assistants"
    status: str = "pending"


class ArtifactManifest(BaseModel):
    files: List[ArtifactRecord] = Field(default_factory=list)

    def add_record(self, path: str, *, file_id: Optional[str], purpose: str, status: str) -> None:
        self.files.append(
            ArtifactRecord(
                path=path,
                file_id=file_id,
                purpose=purpose,
                status=status,
            )
        )


class EvalItem(BaseModel):
    task_id: str
    split: str
    round_index: int
    strategy: Optional[str] = None
    repo_snapshot_sha256: Optional[str] = None
    active_clause_id: Optional[str] = None
    contract_items: Union[Dict[str, Any], List[Dict[str, Any]]] = Field(default_factory=dict)
    witnesses: List[Dict[str, Any]] = Field(default_factory=list)
    regression_guard_ids: List[str] = Field(default_factory=list)
    candidate_files: List[str] = Field(default_factory=list)
    context_snippets: List[Any] = Field(default_factory=list)
    raw_edit_payload: str = ""
    outcome: Dict[str, Any] = Field(default_factory=dict)
    row_quality: Dict[str, Any] = Field(default_factory=dict)
    oracle_patch_present: Optional[bool] = None
    source_paths: Dict[str, str] = Field(default_factory=dict)


class BatchRequestMetadata(BaseModel):
    request_id: str
    task_id: str
    split: str
    strategy: str
    clause_id: Optional[str] = None
    seed: int = 0
    row_quality_bucket: Optional[str] = None


class NormalizedBatchResult(BaseModel):
    request_id: str
    task_id: str
    split: str
    strategy: Optional[str] = None
    clause_id: Optional[str] = None
    status: str
    response_id: Optional[str] = None
    response_status: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Dict[str, Any] = Field(default_factory=dict)
    output_text: Optional[str] = None
    parsed_object: Optional[Dict[str, Any]] = None
    parsing_error: Optional[str] = None
    usage_tokens: Optional[int] = None
    error: Optional[str] = None
    malformed_json: bool = False


class GraderSummary(BaseModel):
    run_id: str
    grader: str
    total_requests: int
    success_count: int
    error_count: int
    malformed_json_count: int
    avg_output_tokens: float = 0.0
    batch_status: Optional[str] = None


class FineTuneDatasetStats(BaseModel):
    train_examples: int
    valid_examples: int
    unique_tasks: int
    unique_clause_types: int
    witness_density: float
    avg_payload_length: float
    leakage_warnings: List[str] = Field(default_factory=list)

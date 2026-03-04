from __future__ import annotations

"""Table schema registry and helpers for dynamic database configuration."""

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Tuple


@dataclass(frozen=True)
class TableSchema:
    key: str
    default_name: str
    insert_columns: Tuple[str, ...]
    select_columns: Tuple[str, ...]
    upsert_columns: Tuple[str, ...]
    config_key: str


@dataclass(frozen=True)
class ResolvedTableSchema:
    key: str
    name: str
    insert_columns: Tuple[str, ...]
    select_columns: Tuple[str, ...]
    upsert_columns: Tuple[str, ...]
    config_key: str

    @property
    def insert_clause(self) -> str:
        return ", ".join(self.insert_columns)

    @property
    def select_clause(self) -> str:
        return ", ".join(self.select_columns)


TABLE_SCHEMAS: Dict[str, TableSchema] = {
    "challenges": TableSchema(
        key="challenges",
        default_name="Challenges",
        insert_columns=(
            "challengeId",
            "legacyId",
            "directProjectId",
            "status",
            "trackType",
            "type",
            "name",
            "description",
            "totalPrizeCost",
            "winners",
            "registrationStartDate",
            "registrationEndDate",
            "submissionStartDate",
            "submissionEndDate",
            "startDate",
            "endDate",
            "technologies",
            "numOfSubmissions",
            "numOfRegistrants",
            "forumId",
        ),
        select_columns=(
            "id",
            "challengeId",
            "legacyId",
            "directProjectId",
            "status",
            "trackType",
            "type",
            "name",
            "description",
            "totalPrizeCost",
            "winners",
            "registrationStartDate",
            "registrationEndDate",
            "submissionStartDate",
            "submissionEndDate",
            "startDate",
            "endDate",
            "technologies",
            "numOfSubmissions",
            "numOfRegistrants",
            "forumId",
        ),
        upsert_columns=(
            "legacyId",
            "directProjectId",
            "status",
            "trackType",
            "type",
            "name",
            "description",
            "totalPrizeCost",
            "winners",
            "registrationStartDate",
            "registrationEndDate",
            "submissionStartDate",
            "submissionEndDate",
            "startDate",
            "endDate",
            "technologies",
            "numOfSubmissions",
            "numOfRegistrants",
            "forumId",
        ),
        config_key="TOPCODER_DB_TABLE_CHALLENGES",
    ),
    "challenge_member_mapping": TableSchema(
        key="challenge_member_mapping",
        default_name="Challenge_Member_Mapping",
        insert_columns=(
            "challengeId",
            "legacyId",
            "memberHandle",
            "submission",
            "winningPosition",
        ),
        select_columns=(
            "id",
            "challengeId",
            "legacyId",
            "memberHandle",
            "submission",
            "winningPosition",
        ),
        upsert_columns=(
            "legacyId",
            "submission",
            "winningPosition",
        ),
        config_key="TOPCODER_DB_TABLE_MAPPING",
    ),
    "members": TableSchema(
        key="members",
        default_name="Members",
        insert_columns=(
            "userId",
            "memberHandle",
            "DEVELOP",
            "DESIGN",
            "DATA_SCIENCE",
            "maxRating",
            "track",
            "subTrack",
            "registrations",
            "wins",
            "user_entered",
            "participation_skill",
        ),
        select_columns=(
            "userId",
            "memberHandle",
            "DEVELOP",
            "DESIGN",
            "DATA_SCIENCE",
            "maxRating",
            "track",
            "subTrack",
            "registrations",
            "wins",
            "user_entered",
            "participation_skill",
            "updatedAt",
        ),
        upsert_columns=(
            "userId",
            "DEVELOP",
            "DESIGN",
            "DATA_SCIENCE",
            "maxRating",
            "track",
            "subTrack",
            "registrations",
            "wins",
            "user_entered",
            "participation_skill",
        ),
        config_key="TOPCODER_DB_TABLE_MEMBERS",
    ),
}


class TableRegistry:
    """Resolve table metadata based on configuration overrides."""

    def __init__(self, overrides: Mapping[str, str] | None = None) -> None:
        overrides = overrides or {}
        resolved: Dict[str, ResolvedTableSchema] = {}

        for schema in TABLE_SCHEMAS.values():
            candidate_names: Iterable[str | None] = (
                overrides.get(schema.config_key),
                overrides.get(f"{schema.key}_table"),
                overrides.get(schema.key),
            )
            table_name = next((name for name in candidate_names if name), schema.default_name)
            resolved[schema.key] = ResolvedTableSchema(
                key=schema.key,
                name=table_name,
                insert_columns=schema.insert_columns,
                select_columns=schema.select_columns,
                upsert_columns=schema.upsert_columns,
                config_key=schema.config_key,
            )

        self._tables: Dict[str, ResolvedTableSchema] = resolved

    def get(self, key: str) -> ResolvedTableSchema:
        if key not in self._tables:
            raise KeyError(f"Unknown table key '{key}'. Valid options: {', '.join(self._tables)}")
        return self._tables[key]

    def all(self) -> Mapping[str, ResolvedTableSchema]:
        return dict(self._tables)

    def to_format_kwargs(self) -> Dict[str, str]:
        """Return placeholders for SQL template formatting."""
        return {f"{schema.key}_table": schema.name for schema in self._tables.values()}

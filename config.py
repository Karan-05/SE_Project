"""Centralized configuration helpers for the data collector."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


def _load_env_file() -> None:
    """Populate os.environ from a local .env file if it exists."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


@dataclass(frozen=True)
class APIConfig:
    base_url: str = os.environ.get("TOPCODER_API_BASE_URL", "https://api.topcoder.com/v5")
    bearer_token: str | None = os.environ.get("TOPCODER_BEARER_TOKEN")


@dataclass(frozen=True)
class DatabaseConfig:
    username: str = os.environ.get("TOPCODER_DB_USER", "root")
    hostname: str = os.environ.get("TOPCODER_DB_HOST", "localhost")
    password: str = os.environ.get("TOPCODER_DB_PASSWORD", "password")
    port: str = os.environ.get("TOPCODER_DB_PORT", "3306")
    database: str = os.environ.get("TOPCODER_DB_NAME", "dataCollector_v2")
    # Backwards-compatible alias for the challenges table.
    table_name: str = os.environ.get("TOPCODER_DB_TABLE", "Challenges")
    challenges_table: str = os.environ.get("TOPCODER_DB_TABLE_CHALLENGES", table_name)
    challenge_member_mapping_table: str = os.environ.get(
        "TOPCODER_DB_TABLE_MAPPING", "Challenge_Member_Mapping"
    )
    members_table: str = os.environ.get("TOPCODER_DB_TABLE_MEMBERS", "Members")

    def as_dict(self) -> Dict[str, str]:
        return {
            "username": self.username,
            "hostname": self.hostname,
            "password": self.password,
            "port": self.port,
            "database": self.database,
            "table_name": self.table_name,
            "challenges_table": self.challenges_table,
            "challenge_member_mapping_table": self.challenge_member_mapping_table,
            "members_table": self.members_table,
        }


def get_storage_directory(default: str | None = None) -> Path | None:
    directory = os.environ.get("TOPCODER_STORAGE_DIR", default)
    return Path(directory).expanduser().resolve() if directory else None


def load_api_config() -> APIConfig:
    return APIConfig()


def load_db_config() -> DatabaseConfig:
    return DatabaseConfig()

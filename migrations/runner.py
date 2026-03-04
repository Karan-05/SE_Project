from __future__ import annotations

"""Simple filesystem-backed migration runner."""

import logging
from pathlib import Path
from typing import Iterable, List, Mapping

from mysql.connector import MySQLConnection

from schema_registry import TableRegistry


class MigrationRunner:
    def __init__(
        self,
        connection: MySQLConnection,
        table_registry: TableRegistry,
        *,
        migrations_path: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.connection = connection
        self.table_registry = table_registry
        self.migrations_path = migrations_path or Path(__file__).resolve().parent
        self.logger = logger or logging.getLogger(__name__)

    def apply(self) -> None:
        cursor = self.connection.cursor()
        self._ensure_tracking_table(cursor)

        applied = self._applied_migrations(cursor)
        available = sorted(self.migrations_path.glob("*.sql"))

        if not available:
            self.logger.warning(
                "No migration files found in %s", self.migrations_path
            )
            return

        for migration_file in available:
            if migration_file.name in applied:
                continue

            self.logger.info("Applying migration %s", migration_file.name)
            sql_template = migration_file.read_text(encoding="utf-8")
            sql = sql_template.format(**self.table_registry.to_format_kwargs())
            statements = list(_split_sql_statements(sql))
            for statement in statements:
                if not statement.strip():
                    continue
                cursor.execute(statement)
            cursor.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (migration_file.name,),
            )
            self.connection.commit()
            self.logger.info(
                "Migration %s applied (%s statements)",
                migration_file.name,
                len(statements),
            )

    def _ensure_tracking_table(self, cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                filename VARCHAR(255) NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def _applied_migrations(cursor) -> List[str]:
        cursor.execute("SELECT filename FROM schema_migrations")
        return [row[0] for row in cursor.fetchall()]


def _split_sql_statements(sql: str) -> Iterable[str]:
    buffer: List[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).rstrip(";")
            yield statement.strip()
            buffer = []
    if buffer:
        statement = "\n".join(buffer).rstrip(";")
        yield statement.strip()

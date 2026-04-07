from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import psycopg
from psycopg.rows import dict_row


class ProcessingStatus(str, Enum):
    DOWNLOADED = "DOWNLOADED"
    PREPROCESSED = "PREPROCESSED"
    INFERRED = "INFERRED"
    FLAGGED = "FLAGGED"
    LABELED = "LABELED"


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is required for shared state tracking.")
    # Psycopg does not accept SQLAlchemy's driver hint.
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def connect() -> psycopg.Connection[Any]:
    return psycopg.connect(_database_url(), row_factory=dict_row)


def ensure_file_state_table(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_processing_state (
            file_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            metadata JSONB
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_file_processing_state_status
            ON file_processing_state (status)
        """
    )
    conn.commit()


def get_status(conn: psycopg.Connection[Any], file_id: str) -> ProcessingStatus | None:
    row = conn.execute(
        "SELECT status FROM file_processing_state WHERE file_id = %s LIMIT 1",
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    return ProcessingStatus(str(row["status"]))


def upsert_status(
    conn: psycopg.Connection[Any],
    *,
    file_id: str,
    status: ProcessingStatus,
    metadata: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        INSERT INTO file_processing_state (file_id, status, updated_at, metadata)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (file_id)
        DO UPDATE SET
            status = EXCLUDED.status,
            updated_at = EXCLUDED.updated_at,
            metadata = EXCLUDED.metadata
        """,
        (file_id, status.value, now, metadata),
    )
    conn.commit()

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from winsshui.models import ConnectionMetadata, HistoryEntry, TerminalLaunchMode


class ConnectionCatalog:
    history_limit = 100

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()
        self._lock = threading.RLock()

    def initialize(self) -> None:
        with self._lock:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                connection.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    PRAGMA busy_timeout = 2000;

                    CREATE TABLE IF NOT EXISTS connection_metadata (
                        alias TEXT PRIMARY KEY COLLATE NOCASE,
                        is_favorite INTEGER NOT NULL DEFAULT 0,
                        group_name TEXT NULL
                    );

                    CREATE TABLE IF NOT EXISTS connection_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        alias TEXT NOT NULL,
                        launched_at_utc TEXT NOT NULL,
                        mode TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS ix_connection_history_launched_at
                        ON connection_history(launched_at_utc DESC);
                    """
                )

    def get_all_metadata(self) -> dict[str, ConnectionMetadata]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT alias, is_favorite, group_name FROM connection_metadata"
            ).fetchall()
        return {
            row["alias"].casefold(): ConnectionMetadata(
                row["alias"], bool(row["is_favorite"]), row["group_name"]
            )
            for row in rows
        }

    def save_metadata(self, metadata: ConnectionMetadata) -> None:
        group_name = metadata.group_name.strip() if metadata.group_name and metadata.group_name.strip() else None
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO connection_metadata(alias, is_favorite, group_name)
                VALUES (?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    is_favorite = excluded.is_favorite,
                    group_name = excluded.group_name
                """,
                (metadata.alias, metadata.is_favorite, group_name),
            )

    def record_launch(
        self,
        alias: str,
        mode: TerminalLaunchMode,
        launched_at_utc: datetime | None = None,
    ) -> None:
        launched_at = launched_at_utc or datetime.now(UTC)
        if launched_at.tzinfo is None:
            launched_at = launched_at.replace(tzinfo=UTC)
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO connection_history(alias, launched_at_utc, mode) VALUES (?, ?, ?)",
                (alias, launched_at.astimezone(UTC).isoformat(), mode.value),
            )
            connection.execute(
                """
                DELETE FROM connection_history
                WHERE id NOT IN (
                    SELECT id FROM connection_history ORDER BY id DESC LIMIT ?
                )
                """,
                (self.history_limit,),
            )

    def get_recent(self, limit: int = 10) -> list[HistoryEntry]:
        if not 1 <= limit <= self.history_limit:
            raise ValueError(f"limit must be between 1 and {self.history_limit}")
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, alias, launched_at_utc, mode
                FROM connection_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            HistoryEntry(row["id"], row["alias"], datetime.fromisoformat(row["launched_at_utc"]), row["mode"])
            for row in rows
        ]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=2.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 2000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

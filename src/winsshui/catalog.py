from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from winsshui.models import (
    ConnectionMetadata,
    ConnectionHealth,
    CommandSnippet,
    HistoryEntry,
    PaneDirection,
    TerminalLaunchMode,
    TunnelPreferences,
    Workspace,
    WorkspaceItem,
)


class ConnectionCatalog:
    history_limit = 100
    session_limit = 30

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
                        group_name TEXT NULL,
                        origin_type TEXT NULL,
                        origin_identifier TEXT NULL,
                        source_fingerprint TEXT NULL,
                        imported_at_utc TEXT NULL,
                        last_synced_at_utc TEXT NULL,
                        icon_name TEXT NULL,
                        notes TEXT NULL,
                        tags TEXT NULL,
                        remote_path TEXT NULL
                    );

                    CREATE TABLE IF NOT EXISTS connection_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        alias TEXT NOT NULL,
                        launched_at_utc TEXT NOT NULL,
                        mode TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS ix_connection_history_launched_at
                        ON connection_history(launched_at_utc DESC);

                    CREATE TABLE IF NOT EXISTS workspaces (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        window_name TEXT NOT NULL DEFAULT 'winsshui'
                    );

                    CREATE TABLE IF NOT EXISTS workspace_items (
                        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        alias TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        split_direction TEXT NOT NULL DEFAULT 'Vertical',
                        split_size REAL NOT NULL DEFAULT 0.5,
                        title TEXT NULL,
                        tab_color TEXT NULL,
                        PRIMARY KEY(workspace_id, position)
                    );

                    CREATE TABLE IF NOT EXISTS command_snippets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        command TEXT NOT NULL,
                        alias TEXT NULL COLLATE NOCASE,
                        UNIQUE(name, alias)
                    );

                    CREATE INDEX IF NOT EXISTS ix_command_snippets_alias
                        ON command_snippets(alias);

                    CREATE TABLE IF NOT EXISTS folder_states (
                        folder_key TEXT PRIMARY KEY,
                        is_expanded INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS tunnel_preferences (
                        alias TEXT PRIMARY KEY COLLATE NOCASE,
                        auto_restart INTEGER NOT NULL DEFAULT 0,
                        start_with_app INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS connection_health (
                        alias TEXT PRIMARY KEY COLLATE NOCASE,
                        checked_at_utc TEXT NOT NULL,
                        status TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        latency_ms INTEGER NULL,
                        last_success_at_utc TEXT NULL
                    );
                    """
                )
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(connection_metadata)").fetchall()
                }
                for name in (
                    "origin_type",
                    "origin_identifier",
                    "source_fingerprint",
                    "imported_at_utc",
                    "last_synced_at_utc",
                    "icon_name",
                    "notes",
                    "tags",
                    "remote_path",
                ):
                    if name not in columns:
                        connection.execute(f"ALTER TABLE connection_metadata ADD COLUMN {name} TEXT NULL")
                workspace_columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(workspaces)").fetchall()
                }
                if "window_name" not in workspace_columns:
                    connection.execute(
                        "ALTER TABLE workspaces ADD COLUMN window_name TEXT NOT NULL DEFAULT 'winsshui'"
                    )
                item_columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(workspace_items)").fetchall()
                }
                item_migrations = {
                    "split_direction": "TEXT NOT NULL DEFAULT 'Vertical'",
                    "split_size": "REAL NOT NULL DEFAULT 0.5",
                    "title": "TEXT NULL",
                    "tab_color": "TEXT NULL",
                }
                for name, definition in item_migrations.items():
                    if name not in item_columns:
                        connection.execute(
                            f"ALTER TABLE workspace_items ADD COLUMN {name} {definition}"
                        )
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_connection_metadata_origin
                    ON connection_metadata(origin_type COLLATE NOCASE, origin_identifier COLLATE NOCASE)
                    WHERE origin_type IS NOT NULL AND origin_identifier IS NOT NULL
                    """
                )

    def get_all_metadata(self) -> dict[str, ConnectionMetadata]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT alias, is_favorite, group_name, origin_type, origin_identifier,
                       source_fingerprint, imported_at_utc, last_synced_at_utc, icon_name,
                       notes, tags, remote_path
                FROM connection_metadata
                """
            ).fetchall()
        return {
            row["alias"].casefold(): ConnectionMetadata(
                row["alias"],
                bool(row["is_favorite"]),
                row["group_name"],
                row["origin_type"],
                row["origin_identifier"],
                row["source_fingerprint"],
                row["imported_at_utc"],
                row["last_synced_at_utc"],
                row["icon_name"],
                row["notes"],
                self._decode_tags(row["tags"]),
                row["remote_path"],
            )
            for row in rows
        }

    def save_metadata(self, metadata: ConnectionMetadata) -> None:
        group_name = metadata.group_name.strip() if metadata.group_name and metadata.group_name.strip() else None
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO connection_metadata(
                    alias, is_favorite, group_name, origin_type, origin_identifier,
                    source_fingerprint, imported_at_utc, last_synced_at_utc, icon_name,
                    notes, tags, remote_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    is_favorite = excluded.is_favorite,
                    group_name = excluded.group_name,
                    origin_type = excluded.origin_type,
                    origin_identifier = excluded.origin_identifier,
                    source_fingerprint = excluded.source_fingerprint,
                    imported_at_utc = excluded.imported_at_utc,
                    last_synced_at_utc = excluded.last_synced_at_utc,
                    icon_name = excluded.icon_name,
                    notes = excluded.notes,
                    tags = excluded.tags,
                    remote_path = excluded.remote_path
                """,
                (
                    metadata.alias,
                    metadata.is_favorite,
                    group_name,
                    metadata.origin_type,
                    metadata.origin_identifier,
                    metadata.source_fingerprint,
                    metadata.imported_at_utc,
                    metadata.last_synced_at_utc,
                    metadata.icon_name,
                    self._normalize_notes(metadata.notes),
                    self._encode_tags(metadata.tags),
                    self._normalize_remote_path(metadata.remote_path),
                ),
            )

    def replace_metadata(self, original_alias: str, metadata: ConnectionMetadata) -> None:
        group_name = metadata.group_name.strip() if metadata.group_name and metadata.group_name.strip() else None
        with self._lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM connection_metadata WHERE alias = ? COLLATE NOCASE",
                (original_alias,),
            )
            connection.execute(
                """
                INSERT INTO connection_metadata(
                    alias, is_favorite, group_name, origin_type, origin_identifier,
                    source_fingerprint, imported_at_utc, last_synced_at_utc, icon_name,
                    notes, tags, remote_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    is_favorite = excluded.is_favorite,
                    group_name = excluded.group_name,
                    origin_type = excluded.origin_type,
                    origin_identifier = excluded.origin_identifier,
                    source_fingerprint = excluded.source_fingerprint,
                    imported_at_utc = excluded.imported_at_utc,
                    last_synced_at_utc = excluded.last_synced_at_utc,
                    icon_name = excluded.icon_name,
                    notes = excluded.notes,
                    tags = excluded.tags,
                    remote_path = excluded.remote_path
                """,
                (
                    metadata.alias,
                    metadata.is_favorite,
                    group_name,
                    metadata.origin_type,
                    metadata.origin_identifier,
                    metadata.source_fingerprint,
                    metadata.imported_at_utc,
                    metadata.last_synced_at_utc,
                    metadata.icon_name,
                    self._normalize_notes(metadata.notes),
                    self._encode_tags(metadata.tags),
                    self._normalize_remote_path(metadata.remote_path),
                ),
            )
            if original_alias.casefold() != metadata.alias.casefold():
                connection.execute(
                    "UPDATE connection_history SET alias = ? WHERE alias = ? COLLATE NOCASE",
                    (metadata.alias, original_alias),
                )
                connection.execute(
                    "UPDATE command_snippets SET alias = ? WHERE alias = ? COLLATE NOCASE",
                    (metadata.alias, original_alias),
                )
                connection.execute(
                    "UPDATE tunnel_preferences SET alias = ? WHERE alias = ? COLLATE NOCASE",
                    (metadata.alias, original_alias),
                )
                connection.execute(
                    "UPDATE connection_health SET alias = ? WHERE alias = ? COLLATE NOCASE",
                    (metadata.alias, original_alias),
                )

    def delete_metadata(self, alias: str) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM connection_metadata WHERE alias = ? COLLATE NOCASE",
                (alias,),
            )
            connection.execute(
                "DELETE FROM command_snippets WHERE alias = ? COLLATE NOCASE",
                (alias,),
            )
            connection.execute(
                "DELETE FROM tunnel_preferences WHERE alias = ? COLLATE NOCASE",
                (alias,),
            )
            connection.execute(
                "DELETE FROM connection_health WHERE alias = ? COLLATE NOCASE",
                (alias,),
            )

    def get_tunnel_preferences(self) -> dict[str, TunnelPreferences]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT alias, auto_restart, start_with_app FROM tunnel_preferences"
            ).fetchall()
        return {
            row["alias"].casefold(): TunnelPreferences(
                row["alias"], bool(row["auto_restart"]), bool(row["start_with_app"])
            )
            for row in rows
        }

    def save_tunnel_preferences(self, preferences: TunnelPreferences) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO tunnel_preferences(alias, auto_restart, start_with_app)
                VALUES (?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    auto_restart = excluded.auto_restart,
                    start_with_app = excluded.start_with_app
                """,
                (preferences.alias, preferences.auto_restart, preferences.start_with_app),
            )

    def get_connection_health(self) -> dict[str, ConnectionHealth]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT alias, checked_at_utc, status, summary, latency_ms, last_success_at_utc "
                "FROM connection_health"
            ).fetchall()
        return {
            row["alias"].casefold(): ConnectionHealth(
                row["alias"],
                row["checked_at_utc"],
                row["status"],
                row["summary"],
                row["latency_ms"],
                row["last_success_at_utc"],
            )
            for row in rows
        }

    def save_connection_health(self, health: ConnectionHealth) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO connection_health(
                    alias, checked_at_utc, status, summary, latency_ms, last_success_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    checked_at_utc = excluded.checked_at_utc,
                    status = excluded.status,
                    summary = excluded.summary,
                    latency_ms = excluded.latency_ms,
                    last_success_at_utc = excluded.last_success_at_utc
                """,
                (
                    health.alias,
                    health.checked_at_utc,
                    health.status,
                    health.summary,
                    health.latency_ms,
                    health.last_success_at_utc,
                ),
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
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = 'session.current'"
            ).fetchone()
            session = self._decode_session(None if row is None else row["value"])
            session.append((alias, mode))
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES ('session.current', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (self._encode_session(session[-self.session_limit :]),),
            )

    def begin_session(self) -> tuple[tuple[str, TerminalLaunchMode], ...]:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = 'session.current'"
            ).fetchone()
            previous = self._decode_session(None if row is None else row["value"])
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES ('session.previous', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (self._encode_session(previous),),
            )
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES ('session.current', '[]') "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            )
        return tuple(previous)

    def get_previous_session(self) -> tuple[tuple[str, TerminalLaunchMode], ...]:
        return self._get_session_setting("session.previous")

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

    def get_workspaces(self) -> list[Workspace]:
        with self._lock, self._connection() as connection:
            workspace_rows = connection.execute(
                "SELECT id, name, window_name FROM workspaces ORDER BY name COLLATE NOCASE"
            ).fetchall()
            item_rows = connection.execute(
                """
                SELECT workspace_id, alias, mode, split_direction, split_size, title, tab_color
                FROM workspace_items
                ORDER BY workspace_id, position
                """
            ).fetchall()
        items_by_workspace: dict[int, list[WorkspaceItem]] = {}
        for row in item_rows:
            try:
                mode = TerminalLaunchMode(row["mode"])
            except ValueError:
                mode = TerminalLaunchMode.NEW_TAB
            try:
                direction = PaneDirection(row["split_direction"])
            except ValueError:
                direction = PaneDirection.VERTICAL
            items_by_workspace.setdefault(row["workspace_id"], []).append(
                WorkspaceItem(
                    row["alias"],
                    mode,
                    direction,
                    float(row["split_size"]),
                    row["title"],
                    row["tab_color"],
                )
            )
        return [
            Workspace(
                row["id"],
                row["name"],
                tuple(items_by_workspace.get(row["id"], [])),
                row["window_name"] or "winsshui",
            )
            for row in workspace_rows
        ]

    def save_workspace(
        self,
        name: str,
        items: tuple[WorkspaceItem, ...],
        window_name: str = "winsshui",
    ) -> Workspace:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Укажите название рабочего пространства")
        if not items:
            raise ValueError("Выберите хотя бы одно подключение")
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO workspaces(name, window_name) VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    name = excluded.name,
                    window_name = excluded.window_name
                """,
                (normalized_name, window_name.strip() or "winsshui"),
            )
            workspace_id = connection.execute(
                "SELECT id FROM workspaces WHERE name = ? COLLATE NOCASE",
                (normalized_name,),
            ).fetchone()["id"]
            connection.execute(
                "DELETE FROM workspace_items WHERE workspace_id = ?",
                (workspace_id,),
            )
            connection.executemany(
                """
                INSERT INTO workspace_items(
                    workspace_id, position, alias, mode, split_direction,
                    split_size, title, tab_color
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        workspace_id,
                        position,
                        item.alias,
                        item.mode.value,
                        item.split_direction.value,
                        max(0.1, min(0.9, item.split_size)),
                        item.title.strip() if item.title and item.title.strip() else None,
                        item.tab_color,
                    )
                    for position, item in enumerate(items)
                ],
            )
        return Workspace(workspace_id, normalized_name, items, window_name.strip() or "winsshui")

    def delete_workspace(self, workspace_id: int) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM workspace_items WHERE workspace_id = ?", (workspace_id,))
            connection.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))

    def get_command_snippets(self, alias: str | None = None) -> list[CommandSnippet]:
        with self._lock, self._connection() as connection:
            if alias is None:
                rows = connection.execute(
                    "SELECT id, name, command, alias FROM command_snippets "
                    "ORDER BY alias IS NOT NULL, name COLLATE NOCASE"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, name, command, alias FROM command_snippets "
                    "WHERE alias IS NULL OR alias = ? COLLATE NOCASE "
                    "ORDER BY alias IS NOT NULL, name COLLATE NOCASE",
                    (alias,),
                ).fetchall()
        return [CommandSnippet(row["id"], row["name"], row["command"], row["alias"]) for row in rows]

    def save_command_snippet(
        self,
        name: str,
        command: str,
        alias: str | None = None,
        snippet_id: int | None = None,
    ) -> CommandSnippet:
        normalized_name = name.strip()
        normalized_command = command.strip()
        normalized_alias = alias.strip() if alias and alias.strip() else None
        if not normalized_name:
            raise ValueError("Укажите название команды")
        if not normalized_command:
            raise ValueError("Введите команду")
        with self._lock, self._connection() as connection:
            if snippet_id is None:
                cursor = connection.execute(
                    "INSERT INTO command_snippets(name, command, alias) VALUES (?, ?, ?)",
                    (normalized_name, normalized_command, normalized_alias),
                )
                snippet_id = int(cursor.lastrowid)
            else:
                cursor = connection.execute(
                    "UPDATE command_snippets SET name = ?, command = ?, alias = ? WHERE id = ?",
                    (normalized_name, normalized_command, normalized_alias, snippet_id),
                )
                if cursor.rowcount == 0:
                    raise LookupError("Командный сниппет не найден")
        return CommandSnippet(snippet_id, normalized_name, normalized_command, normalized_alias)

    def delete_command_snippet(self, snippet_id: int) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM command_snippets WHERE id = ?", (snippet_id,))

    def get_folder_states(self) -> dict[str, bool]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT folder_key, is_expanded FROM folder_states"
            ).fetchall()
        return {row["folder_key"]: bool(row["is_expanded"]) for row in rows}

    def save_folder_state(self, folder_key: str, is_expanded: bool) -> None:
        normalized = folder_key.strip()
        if not normalized:
            return
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO folder_states(folder_key, is_expanded) VALUES (?, ?) "
                "ON CONFLICT(folder_key) DO UPDATE SET is_expanded = excluded.is_expanded",
                (normalized, is_expanded),
            )

    def get_setting(self, key: str) -> str | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def save_setting(self, key: str, value: str) -> None:
        normalized = key.strip()
        if not normalized:
            raise ValueError("Ключ настройки не может быть пустым")
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (normalized, value),
            )

    def _get_session_setting(
        self, key: str
    ) -> tuple[tuple[str, TerminalLaunchMode], ...]:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return tuple(self._decode_session(None if row is None else row["value"]))

    @staticmethod
    def _encode_session(entries: list[tuple[str, TerminalLaunchMode]]) -> str:
        return json.dumps(
            [{"alias": alias, "mode": mode.value} for alias, mode in entries],
            ensure_ascii=False,
        )

    @staticmethod
    def _decode_session(value: str | None) -> list[tuple[str, TerminalLaunchMode]]:
        if not value:
            return []
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(decoded, list):
            return []
        result: list[tuple[str, TerminalLaunchMode]] = []
        for item in decoded:
            if not isinstance(item, dict):
                continue
            alias = item.get("alias")
            mode = item.get("mode")
            if not isinstance(alias, str) or not alias.strip():
                continue
            try:
                launch_mode = TerminalLaunchMode(mode)
            except (TypeError, ValueError):
                launch_mode = TerminalLaunchMode.NEW_TAB
            result.append((alias.strip(), launch_mode))
        return result

    @staticmethod
    def _normalize_notes(notes: str | None) -> str | None:
        normalized = notes.strip() if notes else ""
        return normalized or None

    @staticmethod
    def _normalize_remote_path(remote_path: str | None) -> str | None:
        normalized = remote_path.strip() if remote_path else ""
        if "\r" in normalized or "\n" in normalized:
            raise ValueError("Удалённый путь не может содержать перевод строки")
        return normalized or None

    @staticmethod
    def _encode_tags(tags: tuple[str, ...]) -> str | None:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            value = tag.strip()
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                normalized.append(value)
        return json.dumps(normalized, ensure_ascii=False) if normalized else None

    @staticmethod
    def _decode_tags(value: str | None) -> tuple[str, ...]:
        if not value:
            return ()
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        if not isinstance(decoded, list):
            return ()
        return tuple(str(tag).strip() for tag in decoded if str(tag).strip())

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

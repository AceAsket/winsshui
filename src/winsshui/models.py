from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TerminalLaunchMode(StrEnum):
    NEW_TAB = "NewTab"
    SPLIT_RIGHT = "SplitRight"


@dataclass(frozen=True, slots=True)
class SshHost:
    alias: str
    hostname: str | None = None
    user: str | None = None
    port: int | None = None
    identity_file: str | None = None
    proxy_jump: str | None = None
    connect_timeout: int | None = None
    server_alive_interval: int | None = None
    server_alive_count_max: int | None = None
    forward_agent: bool | None = None
    compression: bool | None = None
    request_tty: str | None = None
    remote_command: str | None = None
    local_forwards: tuple[str, ...] = ()
    remote_forwards: tuple[str, ...] = ()
    dynamic_forwards: tuple[str, ...] = ()
    source_path: str | None = None

    @property
    def display_endpoint(self) -> str:
        destination = self.hostname or self.alias
        endpoint = f"{self.user}@{destination}" if self.user else destination
        return endpoint if self.port in (None, 22) else f"{endpoint}:{self.port}"


@dataclass(frozen=True, slots=True)
class EffectiveSshConfiguration:
    alias: str
    hostname: str
    user: str
    port: int = 22
    identity_files: tuple[str, ...] = ()
    proxy_jump: str | None = None

    @property
    def endpoint(self) -> str:
        endpoint = f"{self.user}@{self.hostname}"
        return endpoint if self.port == 22 else f"{endpoint}:{self.port}"

    @property
    def identity_file(self) -> str:
        return self.identity_files[0] if self.identity_files else "Определяется ssh-agent"


@dataclass(frozen=True, slots=True)
class ConnectionMetadata:
    alias: str
    is_favorite: bool = False
    group_name: str | None = None
    origin_type: str | None = None
    origin_identifier: str | None = None
    source_fingerprint: str | None = None
    imported_at_utc: str | None = None
    last_synced_at_utc: str | None = None
    icon_name: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: int
    alias: str
    launched_at_utc: datetime
    mode: str

    @property
    def local_timestamp(self) -> str:
        return self.launched_at_utc.astimezone().strftime("%d.%m.%Y %H:%M")


@dataclass(frozen=True, slots=True)
class WorkspaceItem:
    alias: str
    mode: TerminalLaunchMode


@dataclass(frozen=True, slots=True)
class Workspace:
    id: int
    name: str
    items: tuple[WorkspaceItem, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandSnippet:
    id: int
    name: str
    command: str
    alias: str | None = None


@dataclass(slots=True)
class ConnectionItem:
    host: SshHost
    is_favorite: bool = False
    group_name: str | None = None
    origin_type: str | None = None
    origin_identifier: str | None = None
    source_fingerprint: str | None = None
    imported_at_utc: str | None = None
    last_synced_at_utc: str | None = None
    icon_name: str | None = None

    @property
    def alias(self) -> str:
        return self.host.alias

    @property
    def group_display(self) -> str:
        return self.group_name or "Без группы"

    def metadata(self) -> ConnectionMetadata:
        return ConnectionMetadata(
            self.alias,
            self.is_favorite,
            self.group_name,
            self.origin_type,
            self.origin_identifier,
            self.source_fingerprint,
            self.imported_at_utc,
            self.last_synced_at_utc,
            self.icon_name,
        )

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


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: int
    alias: str
    launched_at_utc: datetime
    mode: str

    @property
    def local_timestamp(self) -> str:
        return self.launched_at_utc.astimezone().strftime("%d.%m.%Y %H:%M")


@dataclass(slots=True)
class ConnectionItem:
    host: SshHost
    is_favorite: bool = False
    group_name: str | None = None

    @property
    def alias(self) -> str:
        return self.host.alias

    @property
    def group_display(self) -> str:
        return self.group_name or "Без группы"

    def metadata(self) -> ConnectionMetadata:
        return ConnectionMetadata(self.alias, self.is_favorite, self.group_name)


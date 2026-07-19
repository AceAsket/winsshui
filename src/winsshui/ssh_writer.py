from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from winsshui.ssh_config import SshConfigReader


@dataclass(frozen=True, slots=True)
class SshConnectionDraft:
    alias: str
    hostname: str
    user: str | None = None
    port: int = 22
    identity_file: str | None = None
    proxy_jump: str | None = None
    group_name: str | None = None
    is_favorite: bool = False

    def validate(self) -> None:
        if not self.alias or any(character.isspace() for character in self.alias):
            raise ValueError("Алиас обязателен и не должен содержать пробелы")
        if any(character in self.alias for character in "*?![]#"):
            raise ValueError("Алиас не должен содержать * ? ! [ ] или #")
        if not self.hostname.strip():
            raise ValueError("Укажите имя хоста или IP-адрес")
        if not 1 <= self.port <= 65535:
            raise ValueError("Порт должен быть в диапазоне 1–65535")
        if self.identity_file and self.identity_file.casefold().endswith(".ppk"):
            raise ValueError("OpenSSH не поддерживает .ppk: сначала конвертируйте ключ через PuTTYgen")


@dataclass(frozen=True, slots=True)
class WriteResult:
    added: tuple[SshConnectionDraft, ...]
    skipped_aliases: tuple[str, ...]
    backup_path: Path | None


class SshConfigWriter:
    def __init__(self, reader: SshConfigReader | None = None) -> None:
        self.reader = reader or SshConfigReader()

    def append(self, path: Path, draft: SshConnectionDraft) -> WriteResult:
        return self.append_many(path, [draft])

    def append_many(self, path: Path, drafts: list[SshConnectionDraft]) -> WriteResult:
        for draft in drafts:
            draft.validate()

        existing_text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        existing_aliases = {
            host.alias.casefold() for host in self.reader.parse(existing_text.splitlines(), str(path))
        }
        added: list[SshConnectionDraft] = []
        skipped: list[str] = []
        for draft in drafts:
            key = draft.alias.casefold()
            if key in existing_aliases:
                skipped.append(draft.alias)
                continue
            existing_aliases.add(key)
            added.append(draft)

        if not added:
            return WriteResult((), tuple(skipped), None)

        blocks = "\n\n".join(self._format_block(draft) for draft in added)
        prefix = existing_text.rstrip()
        new_text = f"{prefix}\n\n{blocks}\n" if prefix else f"{blocks}\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        backup_path: Path | None = None
        if path.exists():
            backup_path = path.with_name(f"{path.name}.bak")
            shutil.copy2(path, backup_path)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(new_text)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, path)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

        return WriteResult(tuple(added), tuple(skipped), backup_path)

    @classmethod
    def _format_block(cls, draft: SshConnectionDraft) -> str:
        lines = [f"Host {draft.alias}", f"    HostName {cls._quote(draft.hostname.strip())}"]
        if draft.user and draft.user.strip():
            lines.append(f"    User {cls._quote(draft.user.strip())}")
        lines.append(f"    Port {draft.port}")
        if draft.identity_file and draft.identity_file.strip():
            lines.append(f"    IdentityFile {cls._quote(draft.identity_file.strip())}")
        if draft.proxy_jump and draft.proxy_jump.strip():
            lines.append(f"    ProxyJump {cls._quote(draft.proxy_jump.strip())}")
        return "\n".join(lines)

    @staticmethod
    def _quote(value: str) -> str:
        if not any(character.isspace() or character in '#"' for character in value):
            return value
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

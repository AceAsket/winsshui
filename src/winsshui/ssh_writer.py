from __future__ import annotations

import os
import shlex
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
        for name, value in (
            ("ConnectTimeout", self.connect_timeout),
            ("ServerAliveInterval", self.server_alive_interval),
            ("ServerAliveCountMax", self.server_alive_count_max),
        ):
            if value is not None and not 0 <= value <= 86400:
                raise ValueError(f"{name} должен быть в диапазоне 0–86400")
        if self.request_tty not in (None, "no", "yes", "force", "auto"):
            raise ValueError("RequestTTY должен быть no, yes, force или auto")
        if self.remote_command and any(character in self.remote_command for character in "\r\n"):
            raise ValueError("Удалённая команда не должна содержать перевод строки")
        for forwarding in (*self.local_forwards, *self.remote_forwards, *self.dynamic_forwards):
            if not forwarding.strip() or any(character in forwarding for character in "\r\n"):
                raise ValueError("Правило туннеля не должно быть пустым или многострочным")


@dataclass(frozen=True, slots=True)
class WriteResult:
    added: tuple[SshConnectionDraft, ...]
    skipped_aliases: tuple[str, ...]
    backup_path: Path | None


@dataclass(frozen=True, slots=True)
class MutationResult:
    alias: str
    backup_path: Path


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

        backup_path = self._atomic_write(path, new_text)

        return WriteResult(tuple(added), tuple(skipped), backup_path)

    def update(
        self,
        path: Path,
        original_alias: str,
        draft: SshConnectionDraft,
    ) -> MutationResult:
        draft.validate()
        if not path.exists():
            raise FileNotFoundError(path)
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        blocks = self._host_blocks(lines)
        target = next(
            (block for block in blocks if original_alias.casefold() in {a.casefold() for a in block[2]}),
            None,
        )
        if target is None:
            raise LookupError(f"Host {original_alias} не найден в {path}")
        if draft.alias.casefold() != original_alias.casefold():
            aliases = {host.alias.casefold() for host in self.reader.parse(lines, str(path))}
            if draft.alias.casefold() in aliases:
                raise ValueError(f"Host {draft.alias} уже существует")

        start, end, aliases = target
        replacement = self._format_block(draft).splitlines()
        if len(aliases) == 1:
            lines[start:end] = replacement
        else:
            remaining = [alias for alias in aliases if alias.casefold() != original_alias.casefold()]
            lines[start] = f"Host {' '.join(remaining)}"
            while lines and not lines[-1].strip():
                lines.pop()
            lines.extend(["", *replacement])
        backup = self._atomic_write(path, "\n".join(lines).rstrip() + "\n")
        if backup is None:  # path exists by construction
            raise RuntimeError("Не удалось создать резервную копию SSH config")
        return MutationResult(draft.alias, backup)

    def delete(self, path: Path, alias: str) -> MutationResult:
        if not path.exists():
            raise FileNotFoundError(path)
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        target = next(
            (
                block
                for block in self._host_blocks(lines)
                if alias.casefold() in {candidate.casefold() for candidate in block[2]}
            ),
            None,
        )
        if target is None:
            raise LookupError(f"Host {alias} не найден в {path}")
        start, end, aliases = target
        if len(aliases) == 1:
            delete_start = start
            while delete_start > 0 and not lines[delete_start - 1].strip():
                delete_start -= 1
            del lines[delete_start:end]
        else:
            remaining = [candidate for candidate in aliases if candidate.casefold() != alias.casefold()]
            lines[start] = f"Host {' '.join(remaining)}"
        backup = self._atomic_write(path, "\n".join(lines).rstrip() + ("\n" if lines else ""))
        if backup is None:
            raise RuntimeError("Не удалось создать резервную копию SSH config")
        return MutationResult(alias, backup)

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
        if draft.connect_timeout is not None:
            lines.append(f"    ConnectTimeout {draft.connect_timeout}")
        if draft.server_alive_interval is not None:
            lines.append(f"    ServerAliveInterval {draft.server_alive_interval}")
        if draft.server_alive_count_max is not None:
            lines.append(f"    ServerAliveCountMax {draft.server_alive_count_max}")
        if draft.forward_agent is not None:
            lines.append(f"    ForwardAgent {'yes' if draft.forward_agent else 'no'}")
        if draft.compression is not None:
            lines.append(f"    Compression {'yes' if draft.compression else 'no'}")
        if draft.request_tty:
            lines.append(f"    RequestTTY {draft.request_tty}")
        if draft.remote_command and draft.remote_command.strip():
            lines.append(f"    RemoteCommand {cls._quote(draft.remote_command.strip())}")
        for value in draft.local_forwards:
            lines.append(f"    LocalForward {value.strip()}")
        for value in draft.remote_forwards:
            lines.append(f"    RemoteForward {value.strip()}")
        for value in draft.dynamic_forwards:
            lines.append(f"    DynamicForward {value.strip()}")
        return "\n".join(lines)

    @classmethod
    def _host_blocks(cls, lines: list[str]) -> list[tuple[int, int, list[str]]]:
        starts: list[tuple[int, list[str]]] = []
        for index, raw_line in enumerate(lines):
            line = cls.reader_line(raw_line)
            if not line:
                continue
            keyword, value = SshConfigReader._split_directive(line)
            if keyword.casefold() == "host":
                try:
                    aliases = shlex.split(value, posix=True)
                except ValueError:
                    aliases = value.split()
                starts.append((index, aliases))
        return [
            (start, starts[position + 1][0] if position + 1 < len(starts) else len(lines), aliases)
            for position, (start, aliases) in enumerate(starts)
        ]

    @staticmethod
    def reader_line(raw_line: str) -> str:
        return SshConfigReader._remove_comment(raw_line).strip()

    @staticmethod
    def _atomic_write(path: Path, new_text: str) -> Path | None:
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
        return backup_path

    @staticmethod
    def _quote(value: str) -> str:
        if not any(character.isspace() or character in '#"' for character in value):
            return value
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

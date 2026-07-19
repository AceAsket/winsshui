from __future__ import annotations

import posixpath
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TransferCommand:
    program: str
    arguments: tuple[str, ...]
    standard_input: bytes = b""


@dataclass(frozen=True, slots=True)
class RemoteEntry:
    name: str
    is_directory: bool
    size: int | None = None
    details: str = ""


class OpenSshTransferManager:
    def __init__(
        self,
        sftp_path: str | None = None,
        scp_path: str | None = None,
        ssh_path: str | None = None,
    ) -> None:
        self.sftp_path = sftp_path or shutil.which("sftp.exe") or shutil.which("sftp")
        self.scp_path = scp_path or shutil.which("scp.exe") or shutil.which("scp")
        self.ssh_path = ssh_path or shutil.which("ssh.exe") or shutil.which("ssh")

    @property
    def available(self) -> bool:
        return bool((self.sftp_path or self.ssh_path) and self.scp_path)

    def list_command(self, alias: str, remote_path: str) -> TransferCommand:
        if not self.sftp_path:
            raise FileNotFoundError("sftp.exe не найден")
        alias = self._alias(alias)
        path = self.normalize_remote_path(remote_path)
        commands = f"cd {self._batch_quote(path)}\nls -la\nbye\n"
        return TransferCommand(
            self.sftp_path,
            ("-q", "-o", "StrictHostKeyChecking=yes", alias),
            commands.encode("utf-8"),
        )

    def fallback_list_command(self, alias: str, remote_path: str) -> TransferCommand:
        if not self.ssh_path:
            raise FileNotFoundError("ssh.exe не найден")
        alias = self._alias(alias)
        path = self.normalize_remote_path(remote_path)
        remote_command = f"cd {self._shell_quote(path)} && LC_ALL=C ls -la"
        return TransferCommand(
            self.ssh_path,
            ("-o", "StrictHostKeyChecking=yes", alias, remote_command),
        )

    def upload_command(
        self,
        alias: str,
        local_path: Path,
        remote_directory: str,
        recursive: bool = False,
        legacy: bool = False,
    ) -> TransferCommand:
        if not self.scp_path:
            raise FileNotFoundError("scp.exe не найден")
        source = local_path.resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        remote = self.normalize_remote_path(remote_directory)
        arguments = ["-o", "StrictHostKeyChecking=yes"]
        if legacy:
            arguments.append("-O")
        if recursive or source.is_dir():
            arguments.append("-r")
        arguments.extend(
            ["--", str(source), self._scp_remote(self._alias(alias), remote, legacy)]
        )
        return TransferCommand(self.scp_path, tuple(arguments))

    def download_command(
        self,
        alias: str,
        remote_path: str,
        local_directory: Path,
        recursive: bool = False,
        legacy: bool = False,
    ) -> TransferCommand:
        if not self.scp_path:
            raise FileNotFoundError("scp.exe не найден")
        destination = local_directory.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        arguments = ["-o", "StrictHostKeyChecking=yes"]
        if legacy:
            arguments.append("-O")
        if recursive:
            arguments.append("-r")
        remote = self.normalize_remote_path(remote_path)
        arguments.extend(
            ["--", self._scp_remote(self._alias(alias), remote, legacy), str(destination)]
        )
        return TransferCommand(self.scp_path, tuple(arguments))

    @staticmethod
    def needs_legacy_fallback(output: str) -> bool:
        normalized = output.casefold()
        return any(
            marker in normalized
            for marker in (
                "sftp-server: not found",
                "subsystem request failed",
                "unable to start subsystem",
                "couldn't execute subsystem request",
            )
        )

    @staticmethod
    def normalize_remote_path(path: str) -> str:
        normalized = path.strip() or "."
        if "\r" in normalized or "\n" in normalized or "\x00" in normalized:
            raise ValueError("Некорректный удалённый путь")
        normalized = posixpath.normpath(normalized)
        return f"./{normalized}" if normalized.startswith("-") else normalized

    @staticmethod
    def join_remote_path(directory: str, name: str) -> str:
        if not name or "/" in name or "\r" in name or "\n" in name:
            raise ValueError("Некорректное имя удалённого файла")
        return posixpath.join(directory, name)

    @staticmethod
    def parse_listing(output: str) -> tuple[RemoteEntry, ...]:
        entries: list[RemoteEntry] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("sftp>", "total ")):
                continue
            parts = stripped.split(None, 8)
            if len(parts) < 9 or not re.fullmatch(r"[bcdlps-][rwxStTs-]{9}[+@.]?", parts[0]):
                continue
            name = parts[8]
            if " -> " in name:
                name = name.split(" -> ", 1)[0]
            if name in {".", ".."}:
                continue
            try:
                size = int(parts[4])
            except ValueError:
                size = None
            entries.append(RemoteEntry(name, parts[0].startswith("d"), size, stripped))
        return tuple(entries)

    @staticmethod
    def _batch_quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _shell_quote(value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"

    @classmethod
    def _scp_remote(cls, alias: str, path: str, legacy: bool) -> str:
        return f"{alias}:{cls._shell_quote(path) if legacy else path}"

    @staticmethod
    def _alias(alias: str) -> str:
        normalized = alias.strip()
        if not normalized or normalized.startswith("-") or any(c in normalized for c in "\r\n"):
            raise ValueError("Некорректный SSH-алиас")
        return normalized

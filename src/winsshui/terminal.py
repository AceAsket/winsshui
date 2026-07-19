from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from winsshui.models import SshHost, TerminalLaunchMode


@dataclass(frozen=True, slots=True)
class ExternalToolsStatus:
    terminal_path: str | None
    ssh_path: str | None

    @property
    def can_connect(self) -> bool:
        return self.terminal_path is not None and self.ssh_path is not None

    @property
    def message(self) -> str:
        if self.can_connect:
            return "Windows Terminal и OpenSSH готовы"
        if not self.terminal_path and self.ssh_path:
            return "Не найден wt.exe"
        if self.terminal_path and not self.ssh_path:
            return "Не найден ssh.exe"
        return "Не найдены Windows Terminal и OpenSSH"


def detect_tools() -> ExternalToolsStatus:
    return ExternalToolsStatus(shutil.which("wt.exe"), shutil.which("ssh.exe"))


class WindowsTerminalLauncher:
    def create_command(
        self,
        host: SshHost,
        mode: TerminalLaunchMode,
        window_name: str = "winsshui",
    ) -> list[str]:
        if not host.alias.strip() or not window_name.strip():
            raise ValueError("host alias and window name cannot be empty")
        command = ["wt.exe", "-w", window_name]
        command.extend(["split-pane", "-V"] if mode is TerminalLaunchMode.SPLIT_RIGHT else ["new-tab"])
        command.extend(["--title", host.alias, "ssh.exe", host.alias])
        return command

    def launch(self, host: SshHost, mode: TerminalLaunchMode) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            self.create_command(host, mode),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )

    def create_snippet_command(
        self,
        host: SshHost,
        remote_command: str,
        title: str | None = None,
        window_name: str = "winsshui",
    ) -> list[str]:
        normalized = remote_command.strip()
        if not normalized:
            raise ValueError("remote command cannot be empty")
        return [
            "wt.exe",
            "-w",
            window_name,
            "new-tab",
            "--title",
            title or host.alias,
            "ssh.exe",
            "-t",
            "--",
            host.alias,
            normalized,
        ]

    def launch_snippet(
        self,
        host: SshHost,
        remote_command: str,
        title: str | None = None,
    ) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            self.create_snippet_command(host, remote_command, title),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )

    def create_workspace_command(
        self,
        items: list[tuple[SshHost, TerminalLaunchMode]],
        window_name: str = "winsshui",
    ) -> list[str]:
        if not items:
            raise ValueError("workspace cannot be empty")
        command = ["wt.exe", "-w", window_name]
        for index, (host, mode) in enumerate(items):
            if index:
                command.append(";")
            if index == 0 or mode is TerminalLaunchMode.NEW_TAB:
                command.append("new-tab")
            else:
                command.extend(["split-pane", "-V"])
            command.extend(["--title", host.alias, "ssh.exe", host.alias])
        return command

    def launch_workspace(
        self,
        items: list[tuple[SshHost, TerminalLaunchMode]],
    ) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            self.create_workspace_command(items),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )


class ManagedTunnelCommand:
    @staticmethod
    def create(alias: str) -> list[str]:
        if not alias.strip():
            raise ValueError("SSH alias cannot be empty")
        return [
            "-N",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "--",
            alias,
        ]


class WinScpLauncher:
    def __init__(self, executable_path: str | None = None) -> None:
        self.executable_path = executable_path or self.detect()

    @property
    def available(self) -> bool:
        return self.executable_path is not None

    @staticmethod
    def detect() -> str | None:
        direct = shutil.which("WinSCP.exe")
        if direct:
            return direct
        try:
            import winreg

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(
                        hive,
                        r"Software\Microsoft\Windows\CurrentVersion\App Paths\WinSCP.exe",
                    ) as key:
                        registered = str(winreg.QueryValue(key, None)).strip()
                    if registered and Path(registered).exists():
                        return registered
                except OSError:
                    continue
        except ImportError:  # pragma: no cover - Windows application
            pass
        candidates: list[Path] = []
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / "WinSCP" / "WinSCP.exe")
        return str(next((path for path in candidates if path.exists()), "")) or None

    def create_command(self, host: SshHost) -> list[str]:
        if not self.executable_path:
            raise FileNotFoundError("WinSCP.exe не найден")
        hostname = (host.hostname or host.alias).strip()
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        user = f"{quote(host.user, safe='')}@" if host.user else ""
        port = host.port or 22
        url = f"sftp://{user}{hostname}:{port}/"
        command = [self.executable_path, url]
        if host.identity_file:
            identity = str(Path(host.identity_file).expanduser())
            command.append(f"/privatekey={identity}")
        return command

    def launch(self, host: SshHost) -> subprocess.Popen[bytes]:
        return subprocess.Popen(self.create_command(host), close_fds=True)

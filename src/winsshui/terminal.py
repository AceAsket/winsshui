from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

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


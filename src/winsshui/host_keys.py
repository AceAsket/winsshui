from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class KnownHostStatus:
    hostname: str
    port: int
    lookup_target: str
    known_hosts_path: Path
    found: bool
    details: str


@dataclass(frozen=True, slots=True)
class KnownHostRemoval:
    lookup_target: str
    known_hosts_path: Path
    backup_path: Path
    tool_output: str


class KnownHostsManager:
    def __init__(
        self,
        known_hosts_path: Path,
        ssh_keygen_path: str | None = None,
    ) -> None:
        self.known_hosts_path = known_hosts_path
        self.ssh_keygen_path = ssh_keygen_path or shutil.which("ssh-keygen.exe") or shutil.which(
            "ssh-keygen"
        )

    @property
    def available(self) -> bool:
        return self.ssh_keygen_path is not None

    def inspect(self, hostname: str, port: int = 22) -> KnownHostStatus:
        target = self.lookup_target(hostname, port)
        if not self.known_hosts_path.exists():
            return KnownHostStatus(
                hostname.strip(),
                port,
                target,
                self.known_hosts_path,
                False,
                "Файл known_hosts ещё не создан.",
            )
        result = self._run(
            ["-F", target, "-l", "-f", str(self.known_hosts_path)],
            timeout=5.0,
        )
        details = result.stdout.strip()
        if result.returncode == 0 and details:
            return KnownHostStatus(
                hostname.strip(),
                port,
                target,
                self.known_hosts_path,
                True,
                details,
            )
        if result.returncode == 1 and not result.stderr.strip():
            return KnownHostStatus(
                hostname.strip(),
                port,
                target,
                self.known_hosts_path,
                False,
                "Сохранённая запись для этого хоста не найдена.",
            )
        raise RuntimeError(
            result.stderr.strip() or f"ssh-keygen -F завершился с кодом {result.returncode}"
        )

    def remove(self, hostname: str, port: int = 22) -> KnownHostRemoval:
        status = self.inspect(hostname, port)
        if not status.found:
            raise LookupError(f"В {self.known_hosts_path} нет записи для {status.lookup_target}")

        backup_path = self._backup_path()
        shutil.copy2(self.known_hosts_path, backup_path)
        result = self._run(
            ["-R", status.lookup_target, "-f", str(self.known_hosts_path)],
            timeout=10.0,
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip()
                or f"ssh-keygen -R завершился с кодом {result.returncode}; копия: {backup_path}"
            )
        return KnownHostRemoval(
            status.lookup_target,
            self.known_hosts_path,
            backup_path,
            "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part),
        )

    @staticmethod
    def lookup_target(hostname: str, port: int = 22) -> str:
        normalized_host = hostname.strip()
        if normalized_host.startswith("[") and normalized_host.endswith("]"):
            normalized_host = normalized_host[1:-1]
        if not normalized_host or any(character in normalized_host for character in ("\0", "\r", "\n")):
            raise ValueError("Имя SSH-хоста некорректно")
        if not 1 <= port <= 65535:
            raise ValueError("Порт SSH должен быть в диапазоне 1–65535")
        return normalized_host if port == 22 else f"[{normalized_host}]:{port}"

    def _backup_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        return self.known_hosts_path.with_name(
            f"{self.known_hosts_path.name}.winsshui-{timestamp}.bak"
        )

    def _run(self, arguments: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        if not self.ssh_keygen_path:
            raise FileNotFoundError("ssh-keygen.exe не найден в PATH")
        try:
            return subprocess.run(
                [self.ssh_keygen_path, *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exception:
            raise TimeoutError("ssh-keygen не ответил вовремя") from exception

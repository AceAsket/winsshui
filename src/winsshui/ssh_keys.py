from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SshKeyInfo:
    name: str
    private_path: Path | None
    public_path: Path | None
    key_type: str
    fingerprint: str
    loaded_in_agent: bool


class SshKeyManager:
    _safe_name = re.compile(r"^[A-Za-z0-9_.-]+$")

    def __init__(
        self,
        ssh_directory: Path,
        ssh_keygen_path: str | None = None,
        ssh_add_path: str | None = None,
        terminal_path: str | None = None,
    ) -> None:
        self.ssh_directory = ssh_directory.resolve()
        self.ssh_keygen_path = ssh_keygen_path or shutil.which("ssh-keygen.exe") or shutil.which("ssh-keygen")
        self.ssh_add_path = ssh_add_path or shutil.which("ssh-add.exe") or shutil.which("ssh-add")
        self.terminal_path = terminal_path or shutil.which("wt.exe")

    def list_keys(self) -> list[SshKeyInfo]:
        if not self.ssh_directory.exists():
            return []
        loaded = self._loaded_fingerprints()
        public_paths = sorted(self.ssh_directory.glob("*.pub"), key=lambda path: path.name.casefold())
        results: list[SshKeyInfo] = []
        for public_path in public_paths:
            private_path = public_path.with_suffix("")
            key_type = "Неизвестно"
            try:
                first_line = public_path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
                key_type = first_line.split()[0].removeprefix("ssh-").upper()
            except (OSError, IndexError):
                pass
            fingerprint = self.fingerprint(public_path)
            results.append(
                SshKeyInfo(
                    private_path.name,
                    private_path if private_path.is_file() else None,
                    public_path,
                    key_type,
                    fingerprint,
                    fingerprint in loaded,
                )
            )
        return results

    def fingerprint(self, public_path: Path) -> str:
        if not self.ssh_keygen_path:
            return "ssh-keygen не найден"
        completed = subprocess.run(
            [self.ssh_keygen_path, "-lf", str(public_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if completed.returncode != 0:
            return completed.stderr.strip() or "Fingerprint недоступен"
        parts = completed.stdout.strip().split()
        return parts[1] if len(parts) > 1 else completed.stdout.strip()

    def create_key_command(self, name: str, key_type: str, comment: str) -> list[str]:
        if not self.terminal_path or not self.ssh_keygen_path:
            raise FileNotFoundError("Windows Terminal или ssh-keygen.exe не найден")
        target = self._safe_target(name)
        if target.exists() or target.with_suffix(target.suffix + ".pub").exists():
            raise FileExistsError(f"Ключ {target.name} уже существует")
        normalized_type = key_type.casefold()
        if normalized_type not in {"ed25519", "rsa"}:
            raise ValueError("Поддерживаются ключи ED25519 и RSA")
        command = [
            self.terminal_path,
            "new-tab",
            "--title",
            "Создание SSH-ключа",
            self.ssh_keygen_path,
            "-t",
            normalized_type,
            "-f",
            str(target),
        ]
        if normalized_type == "rsa":
            command.extend(["-b", "4096"])
        if comment.strip():
            command.extend(["-C", comment.strip()])
        return command

    def launch_create_key(self, name: str, key_type: str, comment: str) -> subprocess.Popen[bytes]:
        self.ssh_directory.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(self.create_key_command(name, key_type, comment), close_fds=True)

    def add_to_agent_command(self, key: SshKeyInfo) -> list[str]:
        if not self.terminal_path or not self.ssh_add_path:
            raise FileNotFoundError("Windows Terminal или ssh-add.exe не найден")
        if not key.private_path:
            raise FileNotFoundError("Приватная часть ключа не найдена")
        return [
            self.terminal_path,
            "new-tab",
            "--title",
            f"ssh-agent: {key.name}",
            self.ssh_add_path,
            str(key.private_path),
        ]

    def launch_add_to_agent(self, key: SshKeyInfo) -> subprocess.Popen[bytes]:
        return subprocess.Popen(self.add_to_agent_command(key), close_fds=True)

    def remove_from_agent(self, key: SshKeyInfo) -> None:
        if not self.ssh_add_path:
            raise FileNotFoundError("ssh-add.exe не найден")
        if not key.private_path:
            raise FileNotFoundError("Приватная часть ключа не найдена")
        completed = subprocess.run(
            [self.ssh_add_path, "-d", str(key.private_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "ssh-add завершился с ошибкой")

    def _loaded_fingerprints(self) -> set[str]:
        if not self.ssh_add_path:
            return set()
        try:
            completed = subprocess.run(
                [self.ssh_add_path, "-l"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        return {
            part
            for line in completed.stdout.splitlines()
            for part in line.split()
            if part.startswith("SHA256:")
        }

    def _safe_target(self, name: str) -> Path:
        normalized = name.strip()
        if not normalized or not self._safe_name.fullmatch(normalized):
            raise ValueError("Имя ключа может содержать только буквы, цифры, точку, дефис и подчёркивание")
        target = (self.ssh_directory / normalized).resolve()
        if target.parent != self.ssh_directory:
            raise ValueError("Недопустимый путь ключа")
        return target

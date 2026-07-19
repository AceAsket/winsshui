from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiagnosticAssessment:
    level: str
    summary: str


class SshDiagnostics:
    def __init__(self, ssh_path: str | None = None, ssh_add_path: str | None = None) -> None:
        self.ssh_path = ssh_path or shutil.which("ssh.exe") or shutil.which("ssh")
        self.ssh_add_path = ssh_add_path or shutil.which("ssh-add.exe") or shutil.which("ssh-add")

    def connection_command(self, alias: str) -> tuple[str, list[str]]:
        if not self.ssh_path:
            raise FileNotFoundError("ssh.exe не найден в PATH")
        if not alias.strip():
            raise ValueError("SSH-алиас не указан")
        return self.ssh_path, [
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=7",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "RemoteCommand=none",
            "-T",
            "--",
            alias,
            "exit",
        ]

    def agent_command(self) -> tuple[str, list[str]]:
        if not self.ssh_add_path:
            raise FileNotFoundError("ssh-add.exe не найден в PATH")
        return self.ssh_add_path, ["-l"]

    @staticmethod
    def assess_connection(exit_code: int, output: str, timed_out: bool = False) -> DiagnosticAssessment:
        normalized = output.casefold()
        if timed_out:
            return DiagnosticAssessment("error", "Превышено время проверки подключения")
        if exit_code == 0:
            return DiagnosticAssessment("ok", "Подключение и аутентификация работают")
        if "remote host identification has changed" in normalized or "host key verification failed" in normalized:
            return DiagnosticAssessment("danger", "Ошибка проверки ключа сервера")
        if "permission denied" in normalized or "no more authentication methods" in normalized:
            return DiagnosticAssessment(
                "warning",
                "Сервер доступен, но для входа нужна другая или интерактивная аутентификация",
            )
        if "connection refused" in normalized:
            return DiagnosticAssessment("error", "SSH-порт доступен по сети, но соединение отклонено")
        if "could not resolve hostname" in normalized or "name or service not known" in normalized:
            return DiagnosticAssessment("error", "Не удалось разрешить имя хоста")
        if "connection timed out" in normalized or "operation timed out" in normalized:
            return DiagnosticAssessment("error", "Сервер не ответил до истечения ConnectTimeout")
        return DiagnosticAssessment("error", f"SSH завершился с кодом {exit_code}")

    @staticmethod
    def assess_agent(exit_code: int, output: str) -> DiagnosticAssessment:
        normalized = output.casefold()
        if exit_code == 0:
            count = len([line for line in output.splitlines() if line.strip()])
            return DiagnosticAssessment("ok", f"ssh-agent доступен, загружено ключей: {count}")
        if exit_code == 1 or "no identities" in normalized:
            return DiagnosticAssessment("warning", "ssh-agent доступен, но ключи не загружены")
        if "could not open a connection" in normalized or "error connecting to agent" in normalized:
            return DiagnosticAssessment("error", "ssh-agent не запущен или недоступен")
        return DiagnosticAssessment("error", f"ssh-add завершился с кодом {exit_code}")

from __future__ import annotations

import getpass
import glob
import os
import shlex
import subprocess
from collections.abc import Iterable
from pathlib import Path

from winsshui.models import EffectiveSshConfiguration, SshHost


class SshConfigReader:
    _pattern_characters = frozenset("*?[]")

    def read(self, path: Path) -> list[SshHost]:
        hosts: list[SshHost] = []
        seen: set[str] = set()
        for config_path in self.discover_config_files(path):
            for host in self.parse(
                config_path.read_text(encoding="utf-8-sig").splitlines(),
                str(config_path),
            ):
                key = host.alias.casefold()
                if key not in seen:
                    seen.add(key)
                    hosts.append(host)
        return hosts

    def discover_config_files(self, path: Path) -> tuple[Path, ...]:
        root = path.expanduser().resolve()
        discovered: list[Path] = []
        visited: set[str] = set()

        def visit(config_path: Path) -> None:
            resolved = config_path.expanduser().resolve()
            key = str(resolved).casefold()
            if key in visited or not resolved.is_file():
                return
            visited.add(key)
            discovered.append(resolved)
            try:
                lines = resolved.read_text(encoding="utf-8-sig").splitlines()
            except OSError:
                return
            for raw_line in lines:
                line = self._remove_comment(raw_line).strip()
                if not line:
                    continue
                keyword, value = self._split_directive(line)
                if keyword.casefold() != "include":
                    continue
                for pattern in self._tokenize(value):
                    expanded = os.path.expandvars(os.path.expanduser(pattern))
                    candidate = Path(expanded)
                    if not candidate.is_absolute():
                        candidate = resolved.parent / candidate
                    for match in sorted(glob.glob(str(candidate)), key=str.casefold):
                        visit(Path(match))

        visit(root)
        return tuple(discovered)

    def parse(self, lines: Iterable[str], source_path: str | None = None) -> list[SshHost]:
        hosts: list[SshHost] = []
        seen: set[str] = set()
        current: list[dict[str, object]] = []

        def flush() -> None:
            for values in current:
                alias = str(values["alias"])
                key = alias.casefold()
                if key in seen:
                    continue
                seen.add(key)
                hosts.append(SshHost(**values))

        for raw_line in lines:
            line = self._remove_comment(raw_line).strip()
            if not line:
                continue
            keyword, value = self._split_directive(line)
            if keyword.casefold() == "host":
                flush()
                current = [
                    {"alias": alias, "source_path": source_path}
                    for alias in self._tokenize(value)
                    if self._is_concrete_alias(alias)
                ]
                continue
            for values in current:
                self._apply(values, keyword, value)

        flush()
        return hosts

    @staticmethod
    def _remove_comment(line: str) -> str:
        quoted = False
        escaped = False
        for index, character in enumerate(line):
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
            elif character == '"':
                quoted = not quoted
            elif character == "#" and not quoted:
                return line[:index]
        return line

    @staticmethod
    def _split_directive(line: str) -> tuple[str, str]:
        positions = [position for separator in (" ", "\t", "=") if (position := line.find(separator)) >= 0]
        if not positions:
            return line, ""
        separator = min(positions)
        return line[:separator], line[separator:].lstrip(" \t=")

    @staticmethod
    def _tokenize(value: str) -> list[str]:
        try:
            return shlex.split(value, posix=True)
        except ValueError:
            return value.split()

    def _is_concrete_alias(self, alias: str) -> bool:
        return bool(alias) and not alias.startswith("!") and not any(
            character in alias for character in self._pattern_characters
        )

    @staticmethod
    def _apply(values: dict[str, object], keyword: str, value: str) -> None:
        normalized = value.strip()
        if normalized.startswith('"'):
            try:
                tokens = shlex.split(normalized, posix=True)
                normalized = tokens[0] if tokens else ""
            except ValueError:
                normalized = normalized.strip('"')
        key = keyword.casefold()
        field_names = {
            "hostname": "hostname",
            "user": "user",
            "identityfile": "identity_file",
            "proxyjump": "proxy_jump",
            "requesttty": "request_tty",
            "remotecommand": "remote_command",
        }
        integer_fields = {
            "port": ("port", 1, 65535),
            "connecttimeout": ("connect_timeout", 0, 86400),
            "serveraliveinterval": ("server_alive_interval", 0, 86400),
            "serveralivecountmax": ("server_alive_count_max", 0, 86400),
        }
        boolean_fields = {
            "forwardagent": "forward_agent",
            "compression": "compression",
        }
        forwarding_fields = {
            "localforward": "local_forwards",
            "remoteforward": "remote_forwards",
            "dynamicforward": "dynamic_forwards",
        }
        if key in integer_fields:
            field, minimum, maximum = integer_fields[key]
            if field in values:
                return
            try:
                number = int(normalized)
            except ValueError:
                return
            if minimum <= number <= maximum:
                values[field] = number
        elif key in boolean_fields and boolean_fields[key] not in values:
            if normalized.casefold() in ("yes", "no"):
                values[boolean_fields[key]] = normalized.casefold() == "yes"
        elif key in forwarding_fields:
            field = forwarding_fields[key]
            values[field] = (*values.get(field, ()), normalized)
        elif key in field_names:
            values.setdefault(field_names[key], normalized)


class SshConfigurationResolver:
    @staticmethod
    def command(alias: str) -> list[str]:
        if not alias.strip():
            raise ValueError("SSH alias cannot be empty")
        return ["ssh.exe", "-G", "--", alias]

    def resolve(self, alias: str, timeout: float = 5.0) -> EffectiveSshConfiguration:
        result = subprocess.run(
            self.command(alias),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"ssh -G завершился с кодом {result.returncode}")
        return self.parse(alias, result.stdout.splitlines())

    @staticmethod
    def parse(alias: str, lines: Iterable[str]) -> EffectiveSshConfiguration:
        values: dict[str, str] = {}
        identity_files: list[str] = []
        for line in lines:
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            key, value = parts[0].casefold(), parts[1].strip()
            if key == "identityfile":
                identity_files.append(value)
            else:
                values.setdefault(key, value)
        try:
            port = int(values.get("port", "22"))
        except ValueError:
            port = 22
        proxy_jump = values.get("proxyjump")
        if proxy_jump and proxy_jump.casefold() == "none":
            proxy_jump = None
        return EffectiveSshConfiguration(
            alias=alias,
            hostname=values.get("hostname", alias),
            user=values.get("user", getpass.getuser()),
            port=port if 1 <= port <= 65535 else 22,
            identity_files=tuple(identity_files),
            proxy_jump=proxy_jump,
        )

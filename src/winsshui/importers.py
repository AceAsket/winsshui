from __future__ import annotations

import configparser
import os
import re
import shlex
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import unquote

from winsshui.ssh_writer import SshConnectionDraft

try:
    import winreg
except ImportError:  # pragma: no cover - Windows application
    winreg = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    source: str
    name: str
    hostname: str
    user: str | None = None
    port: int = 22
    identity_file: str | None = None
    group_name: str | None = None
    warning: str | None = None

    @property
    def alias(self) -> str:
        base = self.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip() or self.hostname
        normalized = "".join(character if character.isalnum() or character in "._-" else "-" for character in base)
        normalized = re.sub(r"-+", "-", normalized).strip("-.")
        return normalized or "imported-host"

    def to_draft(self) -> SshConnectionDraft:
        return SshConnectionDraft(
            alias=self.alias,
            hostname=self.hostname,
            user=self.user,
            port=self.port,
            identity_file=self.identity_file,
            group_name=self.group_name or self.source,
        )


@dataclass(frozen=True, slots=True)
class ImportScanResult:
    candidates: tuple[ImportCandidate, ...]
    warnings: tuple[str, ...] = ()


class WindowsClientImporter:
    PUTTY_SESSIONS = r"Software\SimonTatham\PuTTY\Sessions"
    WINSCP_SESSIONS = r"Software\Martin Prikryl\WinSCP 2\Sessions"

    def scan_known_sources(self) -> ImportScanResult:
        candidates: list[ImportCandidate] = []
        warnings: list[str] = []
        for importer in (self.import_putty_registry, self.import_winscp_registry):
            try:
                candidates.extend(importer())
            except OSError as exception:
                warnings.append(str(exception))

        for path in self.known_file_paths():
            if not path.exists():
                continue
            try:
                candidates.extend(self.import_file(path))
            except (OSError, ValueError, ET.ParseError, configparser.Error) as exception:
                warnings.append(f"{path}: {exception}")
        return ImportScanResult(tuple(self._deduplicate(candidates)), tuple(warnings))

    @staticmethod
    def known_file_paths() -> tuple[Path, ...]:
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        documents = Path.home() / "Documents"
        return (
            appdata / "WinSCP.ini",
            appdata / "TTYPlus" / "mtputty.xml",
            appdata / "MTPuTTY" / "mtputty.xml",
            documents / "SuperPuTTY" / "Sessions.xml",
            appdata / "SuperPuTTY" / "Sessions.xml",
            appdata / "FileZilla" / "sitemanager.xml",
            appdata / "mRemoteNG" / "confCons.xml",
        )

    def import_putty_registry(self) -> list[ImportCandidate]:
        sessions = self._read_registry_sessions(self.PUTTY_SESSIONS)
        candidates: list[ImportCandidate] = []
        for encoded_name, values in sessions:
            name = unquote(encoded_name)
            if name.casefold() == "default settings":
                continue
            hostname = self._text(values.get("HostName"))
            protocol = self._text(values.get("Protocol"), "ssh").casefold()
            if not hostname or protocol not in ("ssh", "ssh2"):
                continue
            candidates.append(
                self._candidate(
                    "PuTTY",
                    name,
                    hostname,
                    self._text(values.get("UserName")) or None,
                    self._port(values.get("PortNumber")),
                    self._text(values.get("PublicKeyFile")) or None,
                )
            )
        return candidates

    def import_winscp_registry(self) -> list[ImportCandidate]:
        sessions = self._read_registry_sessions(self.WINSCP_SESSIONS)
        candidates: list[ImportCandidate] = []
        for encoded_name, values in sessions:
            name = unquote(encoded_name)
            if name.casefold() == "default settings":
                continue
            hostname = self._text(values.get("HostName"))
            protocol = self._integer(values.get("FSProtocol"), 2)
            if not hostname or protocol > 2:
                continue
            candidates.append(
                self._candidate(
                    "WinSCP",
                    name,
                    hostname,
                    self._text(values.get("UserName")) or None,
                    self._port(values.get("PortNumber")),
                    self._text(values.get("PrivateKeyFile")) or None,
                )
            )
        return candidates

    def import_file(self, path: Path) -> list[ImportCandidate]:
        if path.suffix.casefold() == ".ini":
            return self.import_winscp_ini(path)
        if path.suffix.casefold() not in (".xml", ".config"):
            raise ValueError("Поддерживаются INI и XML-файлы")

        root = ET.parse(path).getroot()
        root_name = self._local_name(root.tag).casefold()
        filename = path.name.casefold()
        if root_name == "mtputty" or "mtputty" in filename:
            return self.parse_mtputty(root)
        if root_name in ("arrayofsessiondata", "sessions") or "sessions" in filename:
            superputty = self.parse_superputty(root)
            if superputty:
                return superputty
        if root_name in ("filezilla3", "servers") or "sitemanager" in filename:
            filezilla = self.parse_filezilla(root)
            if filezilla:
                return filezilla
        if root_name.casefold() in ("mrng:connections", "connections") or "confcons" in filename:
            return self.parse_mremoteng(root)

        for parser in (self.parse_superputty, self.parse_mtputty, self.parse_filezilla, self.parse_mremoteng):
            candidates = parser(root)
            if candidates:
                return candidates
        raise ValueError("Формат XML не распознан")

    def import_winscp_ini(self, path: Path) -> list[ImportCandidate]:
        parser = configparser.RawConfigParser(strict=False)
        parser.optionxform = str
        parser.read(path, encoding="utf-8-sig")
        candidates: list[ImportCandidate] = []
        for section in parser.sections():
            if not section.casefold().startswith("sessions\\"):
                continue
            name = unquote(section.split("\\", 1)[1])
            if name.casefold() == "default settings":
                continue
            values = dict(parser.items(section))
            hostname = self._lookup(values, "HostName")
            protocol = self._integer(self._lookup(values, "FSProtocol"), 2)
            if not hostname or protocol > 2:
                continue
            candidates.append(
                self._candidate(
                    "WinSCP",
                    name,
                    hostname,
                    self._lookup(values, "UserName") or None,
                    self._port(self._lookup(values, "PortNumber")),
                    self._lookup(values, "PrivateKeyFile") or None,
                )
            )
        return candidates

    def parse_mtputty(self, root: ET.Element) -> list[ImportCandidate]:
        candidates: list[ImportCandidate] = []
        for node in root.iter():
            if self._local_name(node.tag).casefold() != "node":
                continue
            fields = {self._local_name(child.tag).casefold(): (child.text or "").strip() for child in node}
            hostname = fields.get("servername", "")
            connection_type = fields.get("puttycontype", "4")
            command_line = fields.get("clparams", "").casefold()
            if not hostname or (connection_type not in ("4", "0") and "-ssh" not in command_line):
                continue
            group = self._xml_parent_group(root, node) or "MTPuTTY"
            candidates.append(
                self._candidate(
                    "MTPuTTY",
                    fields.get("displayname") or hostname,
                    hostname,
                    fields.get("username") or self._user_from_command_line(fields.get("clparams", "")),
                    self._port(fields.get("port")),
                    None,
                    group,
                )
            )
        return candidates

    def parse_superputty(self, root: ET.Element) -> list[ImportCandidate]:
        candidates: list[ImportCandidate] = []
        for element in root.iter():
            attributes = {key.casefold(): value for key, value in element.attrib.items()}
            hostname = attributes.get("host", "").strip()
            protocol = attributes.get("proto", "ssh").casefold()
            if not hostname or protocol not in ("ssh", "ssh2"):
                continue
            name = attributes.get("sessionname") or attributes.get("sessionid") or hostname
            group = name.rsplit("/", 1)[0] if "/" in name else "SuperPuTTY"
            candidates.append(
                self._candidate(
                    "SuperPuTTY",
                    name,
                    hostname,
                    attributes.get("username") or None,
                    self._port(attributes.get("port")),
                    None,
                    group,
                )
            )
        return candidates

    def parse_filezilla(self, root: ET.Element) -> list[ImportCandidate]:
        candidates: list[ImportCandidate] = []
        for server in root.iter():
            if self._local_name(server.tag).casefold() != "server":
                continue
            fields = {self._local_name(child.tag).casefold(): (child.text or "").strip() for child in server}
            if fields.get("protocol") not in ("1", "sftp") or not fields.get("host"):
                continue
            candidates.append(
                self._candidate(
                    "FileZilla SFTP",
                    fields.get("name") or fields["host"],
                    fields["host"],
                    fields.get("user") or None,
                    self._port(fields.get("port")),
                )
            )
        return candidates

    def parse_mremoteng(self, root: ET.Element) -> list[ImportCandidate]:
        candidates: list[ImportCandidate] = []
        for node in root.iter():
            attributes = {key.casefold(): value for key, value in node.attrib.items()}
            if attributes.get("protocol", "").casefold() not in ("ssh", "ssh1", "ssh2"):
                continue
            hostname = attributes.get("hostname", "").strip()
            if not hostname:
                continue
            candidates.append(
                self._candidate(
                    "mRemoteNG",
                    attributes.get("name") or hostname,
                    hostname,
                    attributes.get("username") or None,
                    self._port(attributes.get("port")),
                )
            )
        return candidates

    def _read_registry_sessions(self, key_path: str) -> list[tuple[str, dict[str, object]]]:
        if winreg is None:
            return []
        sessions: list[tuple[str, dict[str, object]]] = []
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            return []
        with root:
            index = 0
            while True:
                try:
                    session_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                values: dict[str, object] = {}
                try:
                    session = winreg.OpenKey(root, session_name)
                except OSError:
                    continue
                with session:
                    value_index = 0
                    while True:
                        try:
                            name, value, _value_type = winreg.EnumValue(session, value_index)
                        except OSError:
                            break
                        value_index += 1
                        values[name] = value
                sessions.append((session_name, values))
        return sessions

    def _candidate(
        self,
        source: str,
        name: str,
        hostname: str,
        user: str | None = None,
        port: int = 22,
        identity_file: str | None = None,
        group_name: str | None = None,
    ) -> ImportCandidate:
        if not user and "@" in hostname and not hostname.startswith("["):
            possible_user, possible_host = hostname.rsplit("@", 1)
            if possible_user and possible_host:
                user, hostname = possible_user, possible_host
        warning = None
        if identity_file and identity_file.casefold().endswith(".ppk"):
            warning = "Ключ .ppk пропущен: конвертируйте его через PuTTYgen в OpenSSH"
            identity_file = None
        normalized_name = name.replace("\\", "/")
        if not group_name and "/" in normalized_name:
            group_name = normalized_name.rsplit("/", 1)[0]
        normalized_group = (group_name or "").replace("\\", "/").strip("/ ")
        if not normalized_group or normalized_group.casefold() == source.casefold():
            destination_folder = source
        elif normalized_group.casefold().startswith(f"{source}/".casefold()):
            destination_folder = normalized_group
        else:
            destination_folder = f"{source}/{normalized_group}"
        return ImportCandidate(
            source,
            name,
            hostname,
            user,
            port,
            identity_file,
            destination_folder,
            warning,
        )

    @staticmethod
    def _deduplicate(candidates: list[ImportCandidate]) -> list[ImportCandidate]:
        result: list[ImportCandidate] = []
        seen: set[tuple[str, str, int, str]] = set()
        aliases: set[str] = set()
        for candidate in candidates:
            endpoint = (
                candidate.hostname.casefold(),
                (candidate.user or "").casefold(),
                candidate.port,
                candidate.source.casefold(),
            )
            if endpoint in seen:
                continue
            seen.add(endpoint)
            alias = candidate.alias
            base = alias
            suffix = 2
            while alias.casefold() in aliases:
                alias = f"{base}-{suffix}"
                suffix += 1
            aliases.add(alias.casefold())
            if alias != candidate.alias:
                candidate = replace(candidate, name=alias)
            result.append(candidate)
        return result

    @staticmethod
    def _lookup(values: dict[str, str], key: str) -> str:
        return next((str(value) for name, value in values.items() if name.casefold() == key.casefold()), "")

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]

    @staticmethod
    def _text(value: object, default: str = "") -> str:
        return str(value).strip() if value is not None else default

    @classmethod
    def _integer(cls, value: object, default: int) -> int:
        try:
            return int(cls._text(value))
        except ValueError:
            return default

    @classmethod
    def _port(cls, value: object) -> int:
        port = cls._integer(value, 22)
        return port if 1 <= port <= 65535 else 22

    @staticmethod
    def _user_from_command_line(command_line: str) -> str | None:
        try:
            tokens = shlex.split(command_line, posix=False)
        except ValueError:
            tokens = command_line.split()
        for index, token in enumerate(tokens[:-1]):
            if token in ("-l", "-login"):
                return tokens[index + 1].strip('"')
        return None

    def _xml_parent_group(self, root: ET.Element, target: ET.Element) -> str | None:
        parent_map = {child: parent for parent in root.iter() for child in parent}
        parent = parent_map.get(target)
        while parent is not None:
            fields = {self._local_name(child.tag).casefold(): (child.text or "").strip() for child in parent}
            display_name = fields.get("displayname")
            if display_name:
                return display_name
            parent = parent_map.get(parent)
        return None

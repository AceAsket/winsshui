from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from winsshui.ssh_config import SshConfigReader


class BackupManager:
    format_version = 1

    def __init__(self, ssh_directory: Path, config_path: Path, catalog_path: Path) -> None:
        self.ssh_directory = ssh_directory.resolve()
        self.config_path = config_path.resolve()
        self.catalog_path = catalog_path.resolve()
        self.reader = SshConfigReader()

    def export(self, archive_path: Path) -> Path:
        destination = archive_path.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        configs = [
            path
            for path in self.reader.discover_config_files(self.config_path)
            if path == self.ssh_directory or self.ssh_directory in path.parents
        ]
        manifest = {
            "format": self.format_version,
            "created_at": datetime.now().astimezone().isoformat(),
            "config_files": [path.relative_to(self.ssh_directory).as_posix() for path in configs],
        }
        temporary_db: Path | None = None
        try:
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                for path in configs:
                    archive.write(path, f"ssh/{path.relative_to(self.ssh_directory).as_posix()}")
                if self.catalog_path.exists():
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as temporary:
                        temporary_db = Path(temporary.name)
                    source = sqlite3.connect(self.catalog_path)
                    target = sqlite3.connect(temporary_db)
                    try:
                        source.backup(target)
                    finally:
                        target.close()
                        source.close()
                    archive.write(temporary_db, "catalog/catalog.db")
        finally:
            if temporary_db and temporary_db.exists():
                temporary_db.unlink()
        return destination

    def restore(self, archive_path: Path) -> tuple[Path, ...]:
        source = archive_path.resolve()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        restored: list[Path] = []
        with zipfile.ZipFile(source, "r") as archive:
            names = set(archive.namelist())
            if "manifest.json" not in names:
                raise ValueError("Архив WinSSH UI не содержит manifest.json")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != self.format_version:
                raise ValueError("Версия архива не поддерживается")
            config_files = manifest.get("config_files")
            if not isinstance(config_files, list):
                raise ValueError("Некорректный список файлов конфигурации")
            for relative_text in config_files:
                relative = PurePosixPath(str(relative_text))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Архив содержит небезопасный путь")
                member = f"ssh/{relative.as_posix()}"
                if member not in names:
                    raise ValueError(f"В архиве отсутствует {member}")
                target = (self.ssh_directory / Path(*relative.parts)).resolve()
                if target != self.ssh_directory and self.ssh_directory not in target.parents:
                    raise ValueError("Архив пытается записать файл вне ~/.ssh")
                self._replace_from_archive(archive, member, target, timestamp)
                restored.append(target)
            if "catalog/catalog.db" in names:
                self._replace_from_archive(
                    archive,
                    "catalog/catalog.db",
                    self.catalog_path,
                    timestamp,
                )
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(f"{self.catalog_path}{suffix}")
                    if sidecar.exists():
                        sidecar.unlink()
                restored.append(self.catalog_path)
        return tuple(restored)

    @staticmethod
    def _replace_from_archive(
        archive: zipfile.ZipFile,
        member: str,
        target: Path,
        timestamp: str,
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copy2(target, target.with_name(f"{target.name}.before-restore-{timestamp}.bak"))
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, dir=target.parent) as output:
                output.write(archive.read(member))
                output.flush()
                os.fsync(output.fileno())
                temporary = Path(output.name)
            os.replace(temporary, target)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

import tempfile
import unittest
from pathlib import Path

from winsshui.backup import BackupManager
from winsshui.catalog import ConnectionCatalog
from winsshui.models import ConnectionMetadata


class BackupManagerTests(unittest.TestCase):
    def test_exports_and_restores_configs_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-backup-") as directory:
            root = Path(directory)
            ssh = root / ".ssh"
            included = ssh / "config.d"
            included.mkdir(parents=True)
            config = ssh / "config"
            child = included / "work.conf"
            config.write_text("Include config.d/*.conf\n", encoding="utf-8")
            child.write_text("Host work\n    HostName old.test\n", encoding="utf-8")
            catalog = ConnectionCatalog(root / "data" / "catalog.db")
            catalog.initialize()
            catalog.save_metadata(ConnectionMetadata("work", True, "Work"))
            manager = BackupManager(ssh, config, catalog.database_path)
            archive = manager.export(root / "backup.zip")

            child.write_text("Host work\n    HostName changed.test\n", encoding="utf-8")
            catalog.save_metadata(ConnectionMetadata("work", False, "Changed"))
            restored = manager.restore(archive)

            self.assertIn(child.resolve(), restored)
            self.assertIn("old.test", child.read_text(encoding="utf-8"))
            self.assertTrue(any(child.parent.glob("work.conf.before-restore-*.bak")))
            loaded = ConnectionCatalog(catalog.database_path)
            loaded.initialize()
            self.assertTrue(loaded.get_all_metadata()["work"].is_favorite)


if __name__ == "__main__":
    unittest.main()

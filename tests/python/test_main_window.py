import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winsshui.models import ConnectionMetadata  # noqa: E402
from winsshui.main_window import MainWindow  # noqa: E402


class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_window_starts_with_empty_ssh_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-ui-tests-") as directory:
            root = Path(directory)
            with (
                patch("winsshui.main_window.Path.home", return_value=root),
                patch.object(MainWindow, "_show_error", side_effect=lambda _title, error: (_ for _ in ()).throw(error)),
            ):
                window = MainWindow(root / "data")
            try:
                self.assertEqual("WinSSH UI", window.windowTitle())
                self.assertEqual(0, window.connection_list.topLevelItemCount())
                self.assertFalse(window.connect_button.isEnabled())
            finally:
                window.close()

    def test_connections_are_split_into_nested_folders(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-ui-tests-") as directory:
            root = Path(directory)
            ssh_directory = root / ".ssh"
            ssh_directory.mkdir()
            (ssh_directory / "config").write_text(
                "Host prod-db\n    HostName db.example.test\n",
                encoding="utf-8",
            )
            with (
                patch("winsshui.main_window.Path.home", return_value=root),
                patch.object(MainWindow, "_show_error", side_effect=lambda _title, error: (_ for _ in ()).throw(error)),
            ):
                window = MainWindow(root / "data")
            try:
                window.catalog.save_metadata(
                    ConnectionMetadata("prod-db", False, "SuperPuTTY/Datacenter")
                )
                window.reload_connections()
                source_folder = window.connection_list.topLevelItem(0)
                nested_folder = source_folder.child(0)
                connection = nested_folder.child(0)
                self.assertIn("SuperPuTTY", source_folder.text(0))
                self.assertIn("Datacenter", nested_folder.text(0))
                self.assertIn("prod-db", connection.text(0))
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from winsshui.importers import ImportCandidate, ImportScanResult  # noqa: E402
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
                self.assertEqual("WinSSH UI 0.7.1", window.version_label.text())
                self.assertEqual("", window.data_button.text())
                self.assertEqual("Данные и настройки", window.data_button.accessibleName())
                self.assertFalse(window.data_button.icon().isNull())
                self.assertEqual(0, window.connection_list.topLevelItemCount())
                self.assertFalse(window.connect_button.isEnabled())
                self.assertFalse(window.host_key_button.isEnabled())
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
                self.assertFalse(source_folder.icon(0).isNull())
                self.assertFalse(connection.icon(0).isNull())

                source_folder.setExpanded(False)
                self.assertFalse(
                    window.catalog.get_folder_states()["folder:superputty"]
                )
                window.reload_connections()
                self.assertFalse(window.connection_list.topLevelItem(0).isExpanded())

                window.icon_combo.setCurrentIndex(window.icon_combo.findData("router"))
                window._save_group()
                self.assertEqual(
                    "router",
                    window.catalog.get_all_metadata()["prod-db"].icon_name,
                )
            finally:
                window.close()

    def test_favorites_are_shown_in_virtual_folder_and_keep_original_group(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-ui-tests-") as directory:
            root = Path(directory)
            ssh_directory = root / ".ssh"
            ssh_directory.mkdir()
            (ssh_directory / "config").write_text(
                "Host favorite\n    HostName favorite.example.test\n\n"
                "Host normal\n    HostName normal.example.test\n",
                encoding="utf-8",
            )
            with (
                patch("winsshui.main_window.Path.home", return_value=root),
                patch.object(MainWindow, "_show_error", side_effect=lambda _title, error: (_ for _ in ()).throw(error)),
            ):
                window = MainWindow(root / "data")
            try:
                window.catalog.save_metadata(
                    ConnectionMetadata("favorite", True, "Production/Web")
                )
                window.reload_connections()
                favorites = window.connection_list.topLevelItem(0)
                self.assertIn("Избранное", favorites.text(0))
                self.assertIn("favorite", favorites.child(0).text(0))
                production = window.connection_list.topLevelItem(1)
                self.assertIn("Production", production.text(0))
                self.assertIn("favorite", production.child(0).child(0).text(0))

                window.search_edit.setText("normal")
                self.assertTrue(
                    all(
                        "Избранное" not in window.connection_list.topLevelItem(index).text(0)
                        for index in range(window.connection_list.topLevelItemCount())
                    )
                )
                window.search_edit.clear()
                favorites = window.connection_list.topLevelItem(0)
                window.connection_list.setCurrentItem(favorites.child(0))
                window._toggle_favorite(False)
                self.assertFalse(window.catalog.get_all_metadata()["favorite"].is_favorite)
                self.assertTrue(
                    all(
                        "Избранное" not in window.connection_list.topLevelItem(index).text(0)
                        for index in range(window.connection_list.topLevelItemCount())
                    )
                )
            finally:
                window.close()

    def test_import_sync_adopts_then_updates_unchanged_local_connection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-ui-tests-") as directory:
            root = Path(directory)
            ssh_directory = root / ".ssh"
            ssh_directory.mkdir()
            (ssh_directory / "config").write_text(
                "Host imported\n    HostName old.example.test\n    User deploy\n    Port 22\n",
                encoding="utf-8",
            )
            with (
                patch("winsshui.main_window.Path.home", return_value=root),
                patch.object(MainWindow, "_show_error", side_effect=lambda _title, error: (_ for _ in ()).throw(error)),
            ):
                window = MainWindow(root / "data")
            try:
                old_candidate = ImportCandidate("WinSCP", "imported", "old.example.test", "deploy")
                with (
                    patch.object(
                        window.client_importer,
                        "scan_known_sources",
                        return_value=ImportScanResult((old_candidate,)),
                    ),
                    patch(
                        "winsshui.main_window.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes,
                    ),
                ):
                    window._sync_imports()
                adopted = window.catalog.get_all_metadata()["imported"]
                self.assertEqual("WinSCP", adopted.origin_type)
                window.catalog.save_metadata(
                    ConnectionMetadata(
                        **{
                            field: getattr(adopted, field)
                            for field in adopted.__dataclass_fields__
                            if field not in ("notes", "tags")
                        },
                        notes="Production jump host",
                        tags=("linux", "critical"),
                    )
                )
                window.reload_connections()
                window.search_edit.setText("critical")
                self.assertIsNotNone(window._selected_connection())
                window.search_edit.clear()

                new_candidate = ImportCandidate("WinSCP", "imported", "new.example.test", "deploy")
                with (
                    patch.object(
                        window.client_importer,
                        "scan_known_sources",
                        return_value=ImportScanResult((new_candidate,)),
                    ),
                    patch(
                        "winsshui.main_window.QMessageBox.question",
                        return_value=QMessageBox.StandardButton.Yes,
                    ),
                ):
                    window._sync_imports()
                self.assertEqual(
                    "new.example.test",
                    window.config_reader.read(ssh_directory / "config")[0].hostname,
                )
                synchronized = window.catalog.get_all_metadata()["imported"]
                self.assertEqual("Production jump host", synchronized.notes)
                self.assertEqual(("linux", "critical"), synchronized.tags)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()

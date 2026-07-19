import tempfile
import sqlite3
import unittest
from datetime import UTC, datetime
from pathlib import Path

from winsshui.catalog import ConnectionCatalog
from winsshui.models import (
    ConnectionMetadata,
    ConnectionHealth,
    PaneDirection,
    TerminalLaunchMode,
    TunnelPreferences,
    WorkspaceItem,
)


class ConnectionCatalogTests(unittest.TestCase):
    def test_metadata_and_history_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            catalog.save_metadata(
                ConnectionMetadata(
                    "prod",
                    True,
                    "Production",
                    icon_name="database",
                    notes="Primary database",
                    tags=("Linux", "Production"),
                    remote_path="/var/lib/app",
                )
            )
            catalog.record_launch(
                "prod",
                TerminalLaunchMode.SPLIT_RIGHT,
                datetime(2026, 7, 19, 10, 30, tzinfo=UTC),
            )
            metadata = catalog.get_all_metadata()["prod"]
            history = catalog.get_recent()
            self.assertTrue(metadata.is_favorite)
            self.assertEqual("Production", metadata.group_name)
            self.assertEqual("database", metadata.icon_name)
            self.assertEqual("Primary database", metadata.notes)
            self.assertEqual(("Linux", "Production"), metadata.tags)
            self.assertEqual("/var/lib/app", metadata.remote_path)
            self.assertEqual("prod", history[0].alias)
            self.assertEqual("SplitRight", history[0].mode)

    def test_history_is_pruned_to_one_hundred_entries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            for index in range(105):
                catalog.record_launch(f"host-{index}", TerminalLaunchMode.NEW_TAB)
            history = catalog.get_recent(100)
            self.assertEqual(100, len(history))
            self.assertEqual("host-104", history[0].alias)
            self.assertEqual("host-5", history[-1].alias)

    def test_import_origin_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            catalog.save_metadata(
                ConnectionMetadata(
                    "prod",
                    False,
                    "WinSCP/Prod",
                    "WinSCP",
                    "Prod/prod",
                    "abc123",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                )
            )
            loaded = catalog.get_all_metadata()["prod"]
            self.assertEqual("WinSCP", loaded.origin_type)
            self.assertEqual("abc123", loaded.source_fingerprint)

    def test_workspace_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            saved = catalog.save_workspace(
                "Production",
                (
                    WorkspaceItem("app", TerminalLaunchMode.NEW_TAB),
                    WorkspaceItem(
                        "db", TerminalLaunchMode.SPLIT_RIGHT,
                        PaneDirection.HORIZONTAL, 0.4, "Database", "#336699",
                    ),
                ),
                "production-window",
            )
            self.assertEqual(saved, catalog.get_workspaces()[0])
            self.assertEqual("production-window", saved.window_name)
            catalog.delete_workspace(saved.id)
            self.assertEqual([], catalog.get_workspaces())

    def test_command_snippets_round_trip_and_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            global_snippet = catalog.save_command_snippet("Uptime", "uptime")
            host_snippet = catalog.save_command_snippet("Logs", "journalctl -n 50", "prod")
            self.assertEqual([global_snippet], catalog.get_command_snippets("other"))
            self.assertEqual(
                {global_snippet.id, host_snippet.id},
                {snippet.id for snippet in catalog.get_command_snippets("PROD")},
            )
            updated = catalog.save_command_snippet(
                "Recent logs", "journalctl -n 100", "prod", host_snippet.id
            )
            self.assertEqual("Recent logs", updated.name)
            catalog.delete_command_snippet(global_snippet.id)
            self.assertEqual([updated], catalog.get_command_snippets("prod"))

    def test_folder_expansion_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            catalog.save_folder_state("folder:production/web", False)
            catalog.save_folder_state("virtual:favorites", True)
            self.assertEqual(
                {"folder:production/web": False, "virtual:favorites": True},
                catalog.get_folder_states(),
            )

    def test_app_setting_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            self.assertIsNone(catalog.get_setting("updates.last_checked_utc"))
            catalog.save_setting("updates.last_checked_utc", "2026-07-19T10:00:00+00:00")
            self.assertEqual(
                "2026-07-19T10:00:00+00:00",
                catalog.get_setting("updates.last_checked_utc"),
            )

    def test_previous_session_is_deduplicated_and_rotated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            self.assertEqual((), catalog.begin_session())
            catalog.record_launch("router", TerminalLaunchMode.NEW_TAB)
            catalog.record_launch("server", TerminalLaunchMode.SPLIT_RIGHT)
            catalog.record_launch("router", TerminalLaunchMode.SPLIT_RIGHT)
            previous = catalog.begin_session()
            self.assertEqual(
                (
                    ("server", TerminalLaunchMode.SPLIT_RIGHT),
                    ("router", TerminalLaunchMode.SPLIT_RIGHT),
                ),
                previous,
            )
            self.assertEqual(previous, catalog.get_previous_session())
            self.assertEqual((), catalog.begin_session())

    def test_tunnel_preferences_follow_alias_and_are_deleted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            catalog.save_metadata(ConnectionMetadata("gateway"))
            catalog.save_tunnel_preferences(TunnelPreferences("gateway", True, True))
            self.assertEqual(
                TunnelPreferences("gateway", True, True),
                catalog.get_tunnel_preferences()["gateway"],
            )
            catalog.replace_metadata("gateway", ConnectionMetadata("gateway-new"))
            self.assertIn("gateway-new", catalog.get_tunnel_preferences())
            catalog.delete_metadata("gateway-new")
            self.assertEqual({}, catalog.get_tunnel_preferences())

    def test_connection_health_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            health = ConnectionHealth(
                "prod", "2026-07-19T20:00:00+00:00", "ok", "Работает", 123,
                "2026-07-19T20:00:00+00:00",
            )
            catalog.save_connection_health(health)
            self.assertEqual(health, catalog.get_connection_health()["prod"])

    def test_initialization_migrates_pre_02_catalog(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            path = Path(directory) / "catalog.db"
            connection = sqlite3.connect(path)
            try:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE connection_metadata (
                            alias TEXT PRIMARY KEY COLLATE NOCASE,
                            is_favorite INTEGER NOT NULL DEFAULT 0,
                            group_name TEXT NULL
                        )
                        """
                    )
                    connection.execute(
                        "INSERT INTO connection_metadata VALUES ('legacy', 1, 'Old')"
                    )
            finally:
                connection.close()
            catalog = ConnectionCatalog(path)
            catalog.initialize()
            loaded = catalog.get_all_metadata()["legacy"]
            self.assertTrue(loaded.is_favorite)
            self.assertIsNone(loaded.origin_type)
            self.assertIsNone(loaded.icon_name)


if __name__ == "__main__":
    unittest.main()

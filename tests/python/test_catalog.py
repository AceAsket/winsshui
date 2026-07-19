import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from winsshui.catalog import ConnectionCatalog
from winsshui.models import ConnectionMetadata, TerminalLaunchMode


class ConnectionCatalogTests(unittest.TestCase):
    def test_metadata_and_history_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-tests-") as directory:
            catalog = ConnectionCatalog(Path(directory) / "catalog.db")
            catalog.initialize()
            catalog.save_metadata(ConnectionMetadata("prod", True, "Production"))
            catalog.record_launch(
                "prod",
                TerminalLaunchMode.SPLIT_RIGHT,
                datetime(2026, 7, 19, 10, 30, tzinfo=UTC),
            )
            metadata = catalog.get_all_metadata()["prod"]
            history = catalog.get_recent()
            self.assertTrue(metadata.is_favorite)
            self.assertEqual("Production", metadata.group_name)
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


if __name__ == "__main__":
    unittest.main()


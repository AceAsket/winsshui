import tempfile
import unittest
from pathlib import Path

from winsshui.ssh_config import SshConfigReader
from winsshui.ssh_writer import SshConfigWriter, SshConnectionDraft


class SshConfigWriterTests(unittest.TestCase):
    def test_creates_config_and_round_trips_connection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-writer-tests-") as directory:
            path = Path(directory) / ".ssh" / "config"
            writer = SshConfigWriter()
            result = writer.append(
                path,
                SshConnectionDraft(
                    alias="prod-web",
                    hostname="10.20.1.15",
                    user="ubuntu",
                    port=2222,
                    identity_file=r"C:\Users\name\.ssh\prod key",
                    proxy_jump="bastion",
                    server_alive_interval=30,
                    forward_agent=True,
                    local_forwards=("127.0.0.1:5432 db:5432",),
                    dynamic_forwards=("1080",),
                ),
            )

            hosts = SshConfigReader().read(path)
            self.assertEqual(1, len(result.added))
            self.assertEqual("ubuntu@10.20.1.15:2222", hosts[0].display_endpoint)
            self.assertEqual(r"C:\Users\name\.ssh\prod key", hosts[0].identity_file)
            self.assertEqual("bastion", hosts[0].proxy_jump)
            self.assertEqual(30, hosts[0].server_alive_interval)
            self.assertTrue(hosts[0].forward_agent)
            self.assertEqual(("127.0.0.1:5432 db:5432",), hosts[0].local_forwards)
            self.assertEqual(("1080",), hosts[0].dynamic_forwards)

    def test_preserves_existing_config_creates_backup_and_skips_duplicate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-writer-tests-") as directory:
            path = Path(directory) / "config"
            original = "Host existing\n    HostName example.test\n"
            path.write_text(original, encoding="utf-8")
            writer = SshConfigWriter()
            result = writer.append_many(
                path,
                [
                    SshConnectionDraft("existing", "ignored.test"),
                    SshConnectionDraft("new-host", "new.example.test"),
                ],
            )

            self.assertEqual(("existing",), result.skipped_aliases)
            self.assertEqual(original, path.with_name("config.bak").read_text(encoding="utf-8"))
            self.assertIn("Host new-host", path.read_text(encoding="utf-8"))

    def test_rejects_unsafe_alias(self) -> None:
        with self.assertRaises(ValueError):
            SshConnectionDraft("bad alias", "example.test").validate()

    def test_updates_single_host_and_preserves_other_blocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-writer-tests-") as directory:
            path = Path(directory) / "config"
            original = (
                "# header\nHost first\n    HostName old.test\n\n"
                "Host untouched\n    HostName untouched.test\n"
            )
            path.write_text(original, encoding="utf-8")
            writer = SshConfigWriter()
            writer.update(path, "first", SshConnectionDraft("renamed", "new.test", port=2200))

            updated = path.read_text(encoding="utf-8")
            self.assertIn("Host renamed\n    HostName new.test\n    Port 2200", updated)
            self.assertIn("Host untouched\n    HostName untouched.test", updated)
            self.assertEqual(original, path.with_name("config.bak").read_text(encoding="utf-8"))

    def test_update_splits_shared_host_and_delete_keeps_other_aliases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-writer-tests-") as directory:
            path = Path(directory) / "config"
            path.write_text("Host one two\n    User shared\n", encoding="utf-8")
            writer = SshConfigWriter()
            writer.update(path, "one", SshConnectionDraft("one", "one.test", user="admin"))
            updated = path.read_text(encoding="utf-8")
            self.assertIn("Host two\n    User shared", updated)
            self.assertIn("Host one\n    HostName one.test", updated)

            writer.delete(path, "one")
            deleted = path.read_text(encoding="utf-8")
            self.assertNotIn("Host one", deleted)
            self.assertIn("Host two", deleted)


if __name__ == "__main__":
    unittest.main()

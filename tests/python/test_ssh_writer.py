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
                ),
            )

            hosts = SshConfigReader().read(path)
            self.assertEqual(1, len(result.added))
            self.assertEqual("ubuntu@10.20.1.15:2222", hosts[0].display_endpoint)
            self.assertEqual(r"C:\Users\name\.ssh\prod key", hosts[0].identity_file)
            self.assertEqual("bastion", hosts[0].proxy_jump)

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


if __name__ == "__main__":
    unittest.main()


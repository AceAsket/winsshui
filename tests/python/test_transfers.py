import tempfile
import unittest
from pathlib import Path

from winsshui.transfers import OpenSshTransferManager


class TransferManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = OpenSshTransferManager("sftp.exe", "scp.exe")

    def test_sftp_listing_uses_stdin_and_strict_host_checking(self) -> None:
        command = self.manager.list_command("prod", "/var/www")
        self.assertEqual("sftp.exe", command.program)
        self.assertIn("StrictHostKeyChecking=yes", command.arguments)
        self.assertNotIn("-b", command.arguments)
        self.assertNotIn("/var/www", command.arguments)
        self.assertIn(b'cd "/var/www"', command.standard_input)
        self.assertTrue(command.standard_input.endswith(b"bye\n"))

    def test_parses_unix_sftp_listing(self) -> None:
        entries = self.manager.parse_listing(
            "drwxr-xr-x 2 root root 4096 Jul 19 10:00 public html\n"
            "-rw-r--r-- 1 root root 123 Jul 19 10:01 index.html\n"
        )
        self.assertEqual(("public html", True), (entries[0].name, entries[0].is_directory))
        self.assertEqual(123, entries[1].size)

    def test_scp_commands_are_argument_lists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "a file.txt"
            source.write_text("test", encoding="utf-8")
            upload = self.manager.upload_command("prod", source, "/tmp")
            download = self.manager.download_command("prod", "/tmp/a file.txt", Path(directory))
        self.assertIn(str(source.resolve()), upload.arguments)
        self.assertIn("prod:/tmp", upload.arguments)
        self.assertIn("prod:/tmp/a file.txt", download.arguments)

    def test_rejects_newlines_in_remote_path(self) -> None:
        with self.assertRaises(ValueError):
            self.manager.list_command("prod", "/tmp\nput bad")


if __name__ == "__main__":
    unittest.main()

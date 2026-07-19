import tempfile
import unittest
import zipfile
from pathlib import Path

from winsshui.logging_utils import export_diagnostics, redact_secrets


class LoggingTests(unittest.TestCase):
    def test_redacts_passwords_and_password_urls(self) -> None:
        text = "password=hunter2 sftp://user:secret@example.test/"
        redacted = redact_secrets(text)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("secret@", redacted)

    def test_diagnostics_archive_excludes_ssh_material(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-log-") as directory:
            root = Path(directory)
            log = root / "winsshui.log"
            log.write_text("password=hidden-value", encoding="utf-8")
            archive_path = export_diagnostics(log, root / "diagnostics.zip")
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual({"system-report.txt", "winsshui.log"}, set(archive.namelist()))
                self.assertNotIn(
                    "hidden-value",
                    archive.read("winsshui.log").decode("utf-8"),
                )


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winsshui.ssh_keys import SshKeyInfo, SshKeyManager


class SshKeyManagerTests(unittest.TestCase):
    def test_builds_interactive_generation_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-keys-") as directory:
            manager = SshKeyManager(
                Path(directory),
                ssh_keygen_path="ssh-keygen.exe",
                ssh_add_path="ssh-add.exe",
                terminal_path="wt.exe",
            )
            command = manager.create_key_command("id_work", "ed25519", "work key")
            self.assertEqual("wt.exe", command[0])
            self.assertIn("ssh-keygen.exe", command)
            self.assertIn("id_work", " ".join(command))
            self.assertNotIn("-N", command)

    def test_rejects_key_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-keys-") as directory:
            manager = SshKeyManager(
                Path(directory), ssh_keygen_path="ssh-keygen.exe", terminal_path="wt.exe"
            )
            with self.assertRaises(ValueError):
                manager.create_key_command("../outside", "ed25519", "")

    def test_lists_public_keys_without_reading_private_material(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-keys-") as directory:
            root = Path(directory)
            private = root / "id_ed25519"
            private.write_text("PRIVATE", encoding="utf-8")
            (root / "id_ed25519.pub").write_text("ssh-ed25519 AAAA test", encoding="utf-8")
            manager = SshKeyManager(root, ssh_keygen_path="ssh-keygen.exe")
            with (
                patch.object(manager, "fingerprint", return_value="SHA256:test"),
                patch.object(manager, "_loaded_fingerprints", return_value={"SHA256:test"}),
            ):
                keys = manager.list_keys()
            self.assertEqual(
                SshKeyInfo(
                    "id_ed25519",
                    manager.ssh_directory / "id_ed25519",
                    manager.ssh_directory / "id_ed25519.pub",
                    "ED25519",
                    "SHA256:test",
                    True,
                ),
                keys[0],
            )


if __name__ == "__main__":
    unittest.main()

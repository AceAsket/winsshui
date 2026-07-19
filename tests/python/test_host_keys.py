import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winsshui.host_keys import KnownHostsManager


class KnownHostsManagerTests(unittest.TestCase):
    def test_formats_standard_and_nonstandard_ports(self) -> None:
        self.assertEqual("server.example", KnownHostsManager.lookup_target("server.example", 22))
        self.assertEqual(
            "[server.example]:2222",
            KnownHostsManager.lookup_target("server.example", 2222),
        )
        self.assertEqual("[2001:db8::1]:2222", KnownHostsManager.lookup_target("2001:db8::1", 2222))

    def test_missing_known_hosts_file_is_reported_without_modification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-host-key-tests-") as directory:
            path = Path(directory) / "known_hosts"
            manager = KnownHostsManager(path, "ssh-keygen.exe")
            status = manager.inspect("server.example")
        self.assertFalse(status.found)
        self.assertIn("ещё не создан", status.details)

    def test_inspects_hashed_entry_through_ssh_keygen(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-host-key-tests-") as directory:
            path = Path(directory) / "known_hosts"
            path.write_text("placeholder\n", encoding="utf-8")
            manager = KnownHostsManager(path, "ssh-keygen.exe")
            completed = subprocess.CompletedProcess(
                [],
                0,
                "# Host server.example found: line 3\nserver.example ED25519 SHA256:abc",
                "",
            )
            with patch("winsshui.host_keys.subprocess.run", return_value=completed) as run:
                status = manager.inspect("server.example", 2222)
        self.assertTrue(status.found)
        self.assertIn("SHA256:abc", status.details)
        self.assertEqual(
            ["ssh-keygen.exe", "-F", "[server.example]:2222", "-l", "-f", str(path)],
            run.call_args.args[0],
        )

    def test_removal_creates_backup_and_uses_exact_argument_list(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-host-key-tests-") as directory:
            path = Path(directory) / "known_hosts"
            original = "server.example ssh-ed25519 AAAATEST\n"
            path.write_text(original, encoding="utf-8")
            manager = KnownHostsManager(path, "ssh-keygen.exe")
            inspect_result = subprocess.CompletedProcess(
                [], 0, "server.example ED25519 SHA256:abc", ""
            )
            remove_result = subprocess.CompletedProcess([], 0, "Host server.example found", "")
            with patch(
                "winsshui.host_keys.subprocess.run",
                side_effect=[inspect_result, remove_result],
            ) as run:
                result = manager.remove("server.example")

            self.assertEqual(original, result.backup_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ["ssh-keygen.exe", "-R", "server.example", "-f", str(path)],
                run.call_args_list[1].args[0],
            )


if __name__ == "__main__":
    unittest.main()

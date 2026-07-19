import unittest

from winsshui.key_install import (
    create_public_key_install_command,
    normalize_public_key,
)


class PublicKeyInstallTests(unittest.TestCase):
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey workstation"

    def test_key_is_sent_only_through_standard_input(self) -> None:
        command = create_public_key_install_command("ssh.exe", "prod", self.key)
        self.assertNotIn(self.key, " ".join(command.arguments))
        self.assertEqual((self.key + "\n").encode(), command.standard_input)
        self.assertIn("StrictHostKeyChecking=yes", command.arguments)
        self.assertNotIn("BatchMode=yes", command.arguments)

    def test_verification_is_noninteractive(self) -> None:
        command = create_public_key_install_command(
            "ssh.exe", "prod", self.key, verify=True, identity_file="C:/keys/id_ed25519"
        )
        self.assertIn("BatchMode=yes", command.arguments)
        self.assertIn("ConnectTimeout=8", command.arguments)
        self.assertNotIn(self.key, " ".join(command.arguments))
        self.assertIn("IdentitiesOnly=yes", command.arguments)
        self.assertIn("C:/keys/id_ed25519", command.arguments)

    def test_rejects_multiline_and_unknown_keys(self) -> None:
        with self.assertRaises(ValueError):
            normalize_public_key(self.key + "\nssh-rsa AAAA")
        with self.assertRaises(ValueError):
            normalize_public_key("unknown AAAA")


if __name__ == "__main__":
    unittest.main()

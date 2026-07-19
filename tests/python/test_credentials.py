import io
import os
import unittest
from unittest.mock import patch

from winsshui import askpass
from winsshui.credentials import StoredCredential, WindowsCredentialStore


class CredentialTests(unittest.TestCase):
    def test_target_name_is_stable_and_does_not_expose_alias(self) -> None:
        first = WindowsCredentialStore.target_name("Production DB")
        second = WindowsCredentialStore.target_name(" production db ")
        self.assertEqual(first, second)
        self.assertNotIn("production", first.casefold())
        self.assertTrue(first.startswith("WinSSHUI:ssh:"))

    def test_askpass_only_answers_password_prompt(self) -> None:
        class FakeStore:
            def read(self, _alias: str) -> StoredCredential:
                return StoredCredential("deploy", "test-secret")

        with (
            patch.dict(os.environ, {"WINSSHUI_CREDENTIAL_ALIAS": "prod"}),
            patch.object(askpass, "WindowsCredentialStore", return_value=FakeStore()),
            patch.object(askpass.sys, "argv", ["askpass", "deploy@prod's password:"]),
            patch.object(askpass.sys, "stdout", io.StringIO()) as output,
        ):
            self.assertEqual(0, askpass.main())
            self.assertEqual("test-secret\n", output.getvalue())

        with (
            patch.dict(os.environ, {"WINSSHUI_CREDENTIAL_ALIAS": "prod"}),
            patch.object(askpass, "WindowsCredentialStore", return_value=FakeStore()),
            patch.object(askpass.sys, "argv", ["askpass", "Accept host key (yes/no)?"]),
        ):
            self.assertEqual(1, askpass.main())


if __name__ == "__main__":
    unittest.main()

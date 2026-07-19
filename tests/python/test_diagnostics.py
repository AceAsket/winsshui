import unittest

from winsshui.diagnostics import SshDiagnostics


class SshDiagnosticsTests(unittest.TestCase):
    def test_connection_command_disables_interactive_authentication(self) -> None:
        program, arguments = SshDiagnostics("ssh.exe", "ssh-add.exe").connection_command("prod")
        self.assertEqual("ssh.exe", program)
        self.assertIn("BatchMode=yes", arguments)
        self.assertEqual(["--", "prod", "exit"], arguments[-3:])

    def test_classifies_host_key_and_authentication_errors(self) -> None:
        host_key = SshDiagnostics.assess_connection(
            255, "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!"
        )
        authentication = SshDiagnostics.assess_connection(255, "Permission denied (publickey).")
        self.assertEqual("danger", host_key.level)
        self.assertEqual("warning", authentication.level)

    def test_classifies_agent_states(self) -> None:
        self.assertEqual("ok", SshDiagnostics.assess_agent(0, "256 SHA256:a key\n").level)
        self.assertEqual("warning", SshDiagnostics.assess_agent(1, "The agent has no identities.").level)
        self.assertEqual(
            "error",
            SshDiagnostics.assess_agent(2, "Error connecting to agent: No such file").level,
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from winsshui.models import PaneDirection, SshHost, TerminalLaunchMode, WorkspaceItem
from winsshui.terminal import ManagedTunnelCommand, WindowsTerminalLauncher, WinScpLauncher


class WindowsTerminalLauncherTests(unittest.TestCase):
    def test_builds_new_tab_as_argument_list(self) -> None:
        command = WindowsTerminalLauncher().create_command(
            SshHost("prod web"), TerminalLaunchMode.NEW_TAB
        )
        self.assertEqual(
            ["wt.exe", "-w", "winsshui", "new-tab", "--title", "prod web", "ssh.exe", "prod web"],
            command,
        )

    def test_builds_split_pane(self) -> None:
        command = WindowsTerminalLauncher().create_command(
            SshHost("db"), TerminalLaunchMode.SPLIT_RIGHT
        )
        self.assertEqual(["split-pane", "-V"], command[3:5])

    def test_builds_remote_snippet_without_local_shell(self) -> None:
        command = WindowsTerminalLauncher().create_snippet_command(
            SshHost("prod"), "journalctl -u nginx -n 20", "Logs"
        )
        self.assertEqual("wt.exe", command[0])
        self.assertEqual(["ssh.exe", "-t", "--", "prod", "journalctl -u nginx -n 20"], command[-5:])
        self.assertNotIn("powershell.exe", command)

    def test_builds_managed_tunnel_without_interactive_prompts(self) -> None:
        command = ManagedTunnelCommand.create("db")
        self.assertIn("BatchMode=yes", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("ExitOnForwardFailure=yes", command)
        self.assertEqual(["--", "db"], command[-2:])

    def test_builds_workspace_with_tabs_and_panes(self) -> None:
        command = WindowsTerminalLauncher().create_workspace_command(
            [
                (SshHost("app"), TerminalLaunchMode.NEW_TAB),
                (SshHost("db"), TerminalLaunchMode.SPLIT_RIGHT),
                (SshHost("logs"), TerminalLaunchMode.NEW_TAB),
            ]
        )
        self.assertEqual(2, command.count(";"))
        self.assertIn("split-pane", command)
        self.assertEqual(2, command.count("new-tab"))

    def test_stored_password_uses_askpass_without_secret_in_arguments(self) -> None:
        launcher = WindowsTerminalLauncher(r"C:\Program Files\WinSSH UI\WinSSH-AskPass.exe")
        with patch("winsshui.terminal.subprocess.Popen") as popen:
            launcher.launch(SshHost("prod"), TerminalLaunchMode.NEW_TAB, "prod")
        arguments = popen.call_args.args[0]
        environment = popen.call_args.kwargs["env"]
        self.assertIn("NumberOfPasswordPrompts=1", arguments)
        self.assertEqual("force", environment["SSH_ASKPASS_REQUIRE"])
        self.assertEqual("prod", environment["WINSSHUI_CREDENTIAL_ALIAS"])
        self.assertNotIn("test-secret", " ".join(arguments))

    def test_workspace_applies_split_size_title_color_and_window(self) -> None:
        command = WindowsTerminalLauncher().create_workspace_command(
            [
                (SshHost("app"), WorkspaceItem("app", TerminalLaunchMode.NEW_TAB)),
                (
                    SshHost("db"),
                    WorkspaceItem(
                        "db", TerminalLaunchMode.SPLIT_RIGHT,
                        PaneDirection.HORIZONTAL, 0.4, "DB", "#336699",
                    ),
                ),
            ],
            "production",
        )
        self.assertEqual(["wt.exe", "-w", "production"], command[:3])
        self.assertIn("-H", command)
        self.assertIn("0.40", command)
        self.assertIn("#336699", command)

    def test_builds_winscp_url_without_password(self) -> None:
        command = WinScpLauncher(r"C:\Tools\WinSCP.exe").create_command(
            SshHost("prod", "2001:db8::1", "deploy user", 2222, r"C:\keys\id key")
        )
        self.assertEqual(r"C:\Tools\WinSCP.exe", command[0])
        self.assertEqual("sftp://deploy%20user@[2001:db8::1]:2222/", command[1])
        self.assertEqual(r"/privatekey=C:\keys\id key", command[2])

    def test_winscp_uses_remote_path_and_new_instance(self) -> None:
        command = WinScpLauncher(r"C:\Tools\WinSCP.exe").create_command(
            SshHost("prod", "prod.test", "deploy"), "/var/www/site files/", True
        )
        self.assertEqual("sftp://deploy@prod.test:22/var/www/site%20files/", command[1])
        self.assertIn("/newinstance", command)


if __name__ == "__main__":
    unittest.main()

import unittest

from winsshui.models import SshHost, TerminalLaunchMode
from winsshui.terminal import WindowsTerminalLauncher


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


if __name__ == "__main__":
    unittest.main()


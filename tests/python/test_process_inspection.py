import unittest
from collections import Counter
from unittest.mock import patch

from winsshui.models import TerminalLaunchMode
from winsshui.process_inspection import (
    exclude_running_sessions,
    running_ssh_alias_counts,
    ssh_destination,
)


class _FakeProcess:
    def __init__(self, name: str, command_line: list[str]) -> None:
        self.info = {"name": name, "cmdline": command_line}


class ProcessInspectionTests(unittest.TestCase):
    def test_extracts_destination_after_ssh_options(self) -> None:
        self.assertEqual(
            "router",
            ssh_destination(
                ["ssh.exe", "-o", "NumberOfPasswordPrompts=1", "-p", "2222", "router"]
            ),
        )
        self.assertEqual(
            "server",
            ssh_destination(["ssh.exe", "-t", "--", "server", "uptime"]),
        )

    def test_counts_running_instances_of_the_same_alias(self) -> None:
        processes = [
            _FakeProcess("ssh.exe", ["ssh.exe", "router"]),
            _FakeProcess("ssh.exe", ["ssh.exe", "-o", "Compression=yes", "router"]),
            _FakeProcess("ssh.exe", ["ssh.exe", "server"]),
            _FakeProcess("notepad.exe", ["notepad.exe", "router"]),
        ]
        with patch("winsshui.process_inspection.psutil.process_iter", return_value=processes):
            self.assertEqual(
                Counter({"router": 2}),
                running_ssh_alias_counts(["router"]),
            )

    def test_excludes_only_the_number_of_sessions_that_are_still_running(self) -> None:
        entries = (
            ("router", TerminalLaunchMode.NEW_TAB),
            ("router", TerminalLaunchMode.SPLIT_RIGHT),
            ("router", TerminalLaunchMode.NEW_TAB),
        )
        self.assertEqual(
            (("router", TerminalLaunchMode.NEW_TAB),),
            exclude_running_sessions(entries, Counter({"router": 2})),
        )
        self.assertEqual((), exclude_running_sessions(entries, Counter({"router": 3})))


if __name__ == "__main__":
    unittest.main()

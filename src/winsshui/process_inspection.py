from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

import psutil

from winsshui.models import TerminalLaunchMode


_SSH_OPTIONS_WITH_VALUE = frozenset(
    {
        "-B",
        "-b",
        "-c",
        "-D",
        "-E",
        "-e",
        "-F",
        "-I",
        "-i",
        "-J",
        "-L",
        "-l",
        "-m",
        "-O",
        "-o",
        "-P",
        "-p",
        "-Q",
        "-R",
        "-S",
        "-W",
        "-w",
    }
)


def ssh_destination(command_line: Sequence[str] | None) -> str | None:
    if not command_line or isinstance(command_line, str) or len(command_line) < 2:
        return None
    index = 1
    while index < len(command_line):
        argument = command_line[index]
        if argument == "--":
            return command_line[index + 1] if index + 1 < len(command_line) else None
        if argument in _SSH_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return argument
    return None


def running_ssh_alias_counts(aliases: Iterable[str]) -> Counter[str]:
    canonical = {alias.casefold(): alias for alias in aliases if alias.strip()}
    result: Counter[str] = Counter()
    if not canonical:
        return result
    try:
        processes = psutil.process_iter(["name", "cmdline"])
        for process in processes:
            try:
                name = Path(str(process.info.get("name") or "")).name.casefold()
                if name not in {"ssh", "ssh.exe"}:
                    continue
                destination = ssh_destination(process.info.get("cmdline"))
                if destination and destination.casefold() in canonical:
                    result[canonical[destination.casefold()]] += 1
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
                continue
    except (psutil.Error, OSError):
        return Counter()
    return result


def exclude_running_sessions(
    entries: Iterable[tuple[str, TerminalLaunchMode]],
    running_counts: Counter[str],
) -> tuple[tuple[str, TerminalLaunchMode], ...]:
    available = Counter(
        {alias.casefold(): max(0, count) for alias, count in running_counts.items()}
    )
    result: list[tuple[str, TerminalLaunchMode]] = []
    for alias, mode in entries:
        key = alias.casefold()
        if available[key] > 0:
            available[key] -= 1
        else:
            result.append((alias, mode))
    return tuple(result)

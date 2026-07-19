from __future__ import annotations

import re
import shlex
import socket
from dataclasses import dataclass

from winsshui.models import SshHost


@dataclass(frozen=True, slots=True)
class TunnelListenEndpoint:
    host: str
    port: int
    kind: str
    specification: str

    @property
    def display(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"


@dataclass(frozen=True, slots=True)
class TunnelPortConflict:
    endpoint: TunnelListenEndpoint
    reason: str


def configured_local_endpoints(host: SshHost) -> tuple[TunnelListenEndpoint, ...]:
    endpoints: list[TunnelListenEndpoint] = []
    for kind, specifications in (
        ("LocalForward", host.local_forwards),
        ("DynamicForward", host.dynamic_forwards),
    ):
        for specification in specifications:
            endpoint = _parse_endpoint(specification, kind)
            if endpoint:
                endpoints.append(endpoint)
    return tuple(endpoints)


def find_port_conflicts(
    endpoints: tuple[TunnelListenEndpoint, ...],
) -> tuple[TunnelPortConflict, ...]:
    conflicts: list[TunnelPortConflict] = []
    for endpoint in endpoints:
        bind_host = endpoint.host
        if bind_host in {"*", ""}:
            bind_host = "0.0.0.0"
        elif bind_host.casefold() == "localhost":
            bind_host = "127.0.0.1"
        family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
        probe = socket.socket(family, socket.SOCK_STREAM)
        try:
            probe.bind((bind_host, endpoint.port))
        except OSError as exception:
            conflicts.append(TunnelPortConflict(endpoint, str(exception)))
        finally:
            probe.close()
    return tuple(conflicts)


def tunnel_summary(host: SshHost) -> str:
    parts = []
    if host.local_forwards:
        parts.append(f"L: {', '.join(host.local_forwards)}")
    if host.remote_forwards:
        parts.append(f"R: {', '.join(host.remote_forwards)}")
    if host.dynamic_forwards:
        parts.append(f"D: {', '.join(host.dynamic_forwards)}")
    return " · ".join(parts)


def _parse_endpoint(specification: str, kind: str) -> TunnelListenEndpoint | None:
    try:
        tokens = shlex.split(specification, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None
    listen = tokens[0]
    if listen.isdecimal():
        port = int(listen)
        return (
            TunnelListenEndpoint("127.0.0.1", port, kind, specification)
            if 1 <= port <= 65535
            else None
        )
    bracketed = re.fullmatch(r"\[([^]]+)]:(\d+)", listen)
    if bracketed:
        bind_host, port_text = bracketed.groups()
    elif ":" in listen:
        bind_host, port_text = listen.rsplit(":", 1)
    else:
        return None
    if not port_text.isdecimal():
        return None
    port = int(port_text)
    if not bind_host or not 1 <= port <= 65535:
        return None
    return TunnelListenEndpoint(bind_host, port, kind, specification)

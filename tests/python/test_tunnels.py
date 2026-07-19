import socket
import unittest

from winsshui.models import SshHost
from winsshui.tunnels import configured_local_endpoints, find_port_conflicts


class TunnelTests(unittest.TestCase):
    def test_parses_local_and_dynamic_listen_endpoints(self) -> None:
        host = SshHost(
            "gateway",
            local_forwards=("8080 internal:80", "[::1]:8443 internal:443"),
            remote_forwards=("9000 localhost:9000",),
            dynamic_forwards=("127.0.0.1:1080",),
        )
        endpoints = configured_local_endpoints(host)
        self.assertEqual(
            [("127.0.0.1", 8080), ("::1", 8443), ("127.0.0.1", 1080)],
            [(endpoint.host, endpoint.port) for endpoint in endpoints],
        )

    def test_detects_occupied_local_port(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        try:
            port = listener.getsockname()[1]
            host = SshHost("gateway", local_forwards=(f"{port} internal:80",))
            conflicts = find_port_conflicts(configured_local_endpoints(host))
            self.assertEqual(1, len(conflicts))
            self.assertEqual(port, conflicts[0].endpoint.port)
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()

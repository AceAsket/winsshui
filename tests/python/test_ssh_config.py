import tempfile
import unittest
from pathlib import Path

from winsshui.ssh_config import SshConfigReader, SshConfigurationResolver


class SshConfigReaderTests(unittest.TestCase):
    def test_parses_concrete_aliases_and_fields(self) -> None:
        hosts = SshConfigReader().parse(
            [
                "Host *",
                "  ServerAliveInterval 30",
                "Host prod-web prod-api",
                "  HostName 10.20.1.15",
                "  User ubuntu",
                "  Port 2222",
                '  IdentityFile "~/.ssh/prod key" # comment',
                "  ProxyJump bastion",
            ],
            "config",
        )
        self.assertEqual(["prod-web", "prod-api"], [host.alias for host in hosts])
        self.assertEqual("ubuntu@10.20.1.15:2222", hosts[0].display_endpoint)
        self.assertEqual("~/.ssh/prod key", hosts[0].identity_file)

    def test_ignores_patterns_and_duplicates(self) -> None:
        hosts = SshConfigReader().parse(
            ["Host *.internal !blocked explicit", " User admin", "Host explicit", " User ignored"]
        )
        self.assertEqual(1, len(hosts))
        self.assertEqual("admin", hosts[0].user)

    def test_reads_include_globs_recursively_and_tracks_source_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-config-") as directory:
            root = Path(directory) / ".ssh"
            included = root / "config.d"
            included.mkdir(parents=True)
            config = root / "config"
            config.write_text(
                "Include config.d/*.conf\nHost root-host\n    HostName root.test\n",
                encoding="utf-8",
            )
            child = included / "production.conf"
            child.write_text(
                "Include ../config\nHost included-host\n    HostName included.test\n",
                encoding="utf-8",
            )
            reader = SshConfigReader()
            hosts = reader.read(config)
            self.assertEqual({"root-host", "included-host"}, {host.alias for host in hosts})
            included_host = next(host for host in hosts if host.alias == "included-host")
            self.assertEqual(str(child.resolve()), included_host.source_path)
            self.assertEqual((config.resolve(), child.resolve()), reader.discover_config_files(config))


class SshConfigurationResolverTests(unittest.TestCase):
    def test_parses_effective_configuration(self) -> None:
        config = SshConfigurationResolver.parse(
            "prod",
            [
                "user deploy",
                "hostname 10.20.1.15",
                "port 2222",
                "identityfile ~/.ssh/id_ed25519",
                "proxyjump bastion",
            ],
        )
        self.assertEqual("deploy@10.20.1.15:2222", config.endpoint)
        self.assertEqual("~/.ssh/id_ed25519", config.identity_file)
        self.assertEqual("bastion", config.proxy_jump)


if __name__ == "__main__":
    unittest.main()

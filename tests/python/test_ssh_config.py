import unittest

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


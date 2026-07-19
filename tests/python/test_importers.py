import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from winsshui.importers import WindowsClientImporter


class WindowsClientImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.importer = WindowsClientImporter()

    def test_parses_mtputty_xml_without_password(self) -> None:
        root = ET.fromstring(
            """
            <MTPutty version="1.7"><Servers><Putty><Node Type="1">
              <DisplayName>Production Router</DisplayName><ServerName>10.0.0.1</ServerName>
              <PuttyConType>4</PuttyConType><Port>2222</Port><UserName>admin</UserName>
              <Password>encrypted-value</Password>
            </Node></Putty></Servers></MTPutty>
            """
        )
        candidate = self.importer.parse_mtputty(root)[0]
        self.assertEqual("Production-Router", candidate.alias)
        self.assertEqual("admin", candidate.user)
        self.assertEqual(2222, candidate.port)
        self.assertNotIn("password", candidate.__dataclass_fields__)

    def test_parses_superputty_sessions(self) -> None:
        root = ET.fromstring(
            '<ArrayOfSessionData><SessionData SessionName="DC/prod-db" Host="db.example.test" '
            'Proto="SSH" Port="22" Username="deploy" /></ArrayOfSessionData>'
        )
        candidate = self.importer.parse_superputty(root)[0]
        self.assertEqual("prod-db", candidate.alias)
        self.assertEqual("SuperPuTTY/DC", candidate.group_name)
        self.assertEqual("deploy", candidate.user)

    def test_parses_winscp_ini_and_warns_about_ppk(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-import-tests-") as directory:
            path = Path(directory) / "WinSCP.ini"
            path.write_text(
                """
[Sessions\\Production%20Web]
HostName=web.example.test
UserName=ubuntu
PortNumber=22
FSProtocol=2
PrivateKeyFile=C:\\keys\\prod.ppk

[Sessions\\FTP site]
HostName=ftp.example.test
FSProtocol=5
""".strip(),
                encoding="utf-8",
            )
            candidates = self.importer.import_winscp_ini(path)
        self.assertEqual(1, len(candidates))
        self.assertEqual("Production-Web", candidates[0].alias)
        self.assertIsNone(candidates[0].identity_file)
        self.assertIn("PuTTYgen", candidates[0].warning or "")

    def test_parses_filezilla_sftp_only(self) -> None:
        root = ET.fromstring(
            """
            <FileZilla3><Servers>
              <Server><Host>sftp.example.test</Host><Port>22</Port><Protocol>1</Protocol>
                <User>alice</User><Name>SFTP Site</Name></Server>
              <Server><Host>ftp.example.test</Host><Port>21</Port><Protocol>0</Protocol>
                <Name>FTP Site</Name></Server>
            </Servers></FileZilla3>
            """
        )
        candidates = self.importer.parse_filezilla(root)
        self.assertEqual(1, len(candidates))
        self.assertEqual("sftp.example.test", candidates[0].hostname)

    def test_parses_plain_mremoteng_ssh_nodes(self) -> None:
        root = ET.fromstring(
            '<Connections><Node Name="SSH server" Protocol="SSH2" Hostname="10.1.1.5" '
            'Username="root" Port="2222" /></Connections>'
        )
        candidate = self.importer.parse_mremoteng(root)[0]
        self.assertEqual("SSH-server", candidate.alias)
        self.assertEqual(2222, candidate.port)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from winsshui.updates import (
    expected_sha256,
    file_sha256,
    is_newer_version,
    parse_latest_release,
    version_parts,
)


class UpdateTests(unittest.TestCase):
    def test_version_comparison(self) -> None:
        self.assertTrue(is_newer_version("v0.5.0", "0.4.0"))
        self.assertFalse(is_newer_version("v0.4.0", "0.4.0"))
        self.assertFalse(is_newer_version("0.3.10", "0.4.0"))
        self.assertEqual((1, 2, 0), version_parts("v1.2"))

    def test_parse_release_selects_windows_executable(self) -> None:
        release = parse_latest_release(
            json.dumps(
                {
                    "tag_name": "v0.5.0",
                    "name": "WinSSH UI 0.5.0",
                    "body": "Изменения",
                    "html_url": "https://github.com/AceAsket/winsshui/releases/tag/v0.5.0",
                    "assets": [
                        {
                            "name": "WinSSH-UI.exe",
                            "browser_download_url": "https://github.com/AceAsket/winsshui/releases/download/v0.5.0/WinSSH-UI.exe",
                            "digest": "sha256:abc",
                        }
                    ],
                }
            )
        )
        self.assertEqual("0.5.0", release.version)
        self.assertTrue(release.download_url.endswith("WinSSH-UI.exe"))
        self.assertEqual("sha256:abc", release.asset_digest)
        self.assertEqual("WinSSH-UI.exe", release.asset_name)

    def test_parse_release_falls_back_to_release_page(self) -> None:
        release = parse_latest_release(
            {
                "tag_name": "v0.5.0",
                "html_url": "https://github.com/AceAsket/winsshui/releases/tag/v0.5.0",
                "assets": [],
            }
        )
        self.assertIsNone(release.download_url)

    def test_prefers_installer_and_validates_sha256_digest(self) -> None:
        digest = "a" * 64
        release = parse_latest_release(
            {
                "tag_name": "v0.5.0",
                "html_url": "https://github.com/AceAsket/winsshui/releases/tag/v0.5.0",
                "assets": [
                    {
                        "name": "WinSSH-UI.exe",
                        "browser_download_url": "https://github.com/download/portable.exe",
                    },
                    {
                        "name": "WinSSH-UI-Setup.exe",
                        "browser_download_url": "https://github.com/download/setup.exe",
                        "digest": f"sha256:{digest}",
                    },
                ],
            }
        )
        self.assertEqual("WinSSH-UI-Setup.exe", release.asset_name)
        self.assertEqual(digest, expected_sha256(release.asset_digest))
        self.assertIsNone(expected_sha256("sha256:broken"))

    def test_rejects_non_https_release_url(self) -> None:
        with self.assertRaises(ValueError):
            parse_latest_release(
                {"tag_name": "v0.5.0", "html_url": "http://example.test/release"}
            )
        with self.assertRaises(ValueError):
            parse_latest_release(
                {"tag_name": "v0.5.0", "html_url": "https://example.test/release"}
            )

    def test_file_sha256(self) -> None:
        with tempfile.TemporaryDirectory(prefix="winsshui-update-") as directory:
            path = Path(directory) / "update.exe"
            path.write_bytes(b"verified update")
            self.assertEqual(
                "59f19f34399b14e5f1628642e9ce341d660094ba76898e4db6b1875f525b6a6a",
                file_sha256(str(path)),
            )


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from winsshui.updates import is_newer_version, parse_latest_release, version_parts


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

    def test_parse_release_falls_back_to_release_page(self) -> None:
        release = parse_latest_release(
            {
                "tag_name": "v0.5.0",
                "html_url": "https://github.com/AceAsket/winsshui/releases/tag/v0.5.0",
                "assets": [],
            }
        )
        self.assertIsNone(release.download_url)

    def test_rejects_non_https_release_url(self) -> None:
        with self.assertRaises(ValueError):
            parse_latest_release(
                {"tag_name": "v0.5.0", "html_url": "http://example.test/release"}
            )


if __name__ == "__main__":
    unittest.main()

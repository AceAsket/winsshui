import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winsshui.embedded_terminal import EmbeddedWindowsTerminalHost  # noqa: E402
from winsshui.terminal import WindowsTerminalLauncher  # noqa: E402


class EmbeddedTerminalHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_monitor_reapplies_container_size(self) -> None:
        host = EmbeddedWindowsTerminalHost(WindowsTerminalLauncher())
        api = Mock()
        api.exists.return_value = True
        host._api = api
        host._terminal_hwnd = 123
        with patch.object(host, "_resize_terminal") as resize:
            host._monitor_window()
        resize.assert_called_once_with()

    def test_close_requests_window_close_without_detaching(self) -> None:
        host = EmbeddedWindowsTerminalHost(WindowsTerminalLauncher())
        api = Mock()
        host._api = api
        host._terminal_hwnd = 123
        host._original_style = 456
        host.close_terminal()
        api.request_close.assert_called_once_with(123)
        api.detach.assert_not_called()
        self.assertIsNone(host._terminal_hwnd)

    def test_resize_converts_qt_logical_size_to_native_pixels(self) -> None:
        host = EmbeddedWindowsTerminalHost(WindowsTerminalLauncher())
        api = Mock()
        host._api = api
        host._terminal_hwnd = 123
        host.surface.resize(800, 500)
        with patch.object(host.surface, "devicePixelRatioF", return_value=1.25):
            host._resize_terminal()
        api.resize.assert_called_once_with(123, 1000, 625)


if __name__ == "__main__":
    unittest.main()

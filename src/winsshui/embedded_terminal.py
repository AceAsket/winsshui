from __future__ import annotations

import ctypes
import os
import time
import uuid
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from winsshui.models import SshHost, TerminalLaunchMode, WorkspaceItem
from winsshui.terminal import WindowsTerminalLauncher


class _Win32WindowApi:
    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    WS_SYSMENU = 0x00080000
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    SWP_SHOWWINDOW = 0x0040
    SW_SHOW = 5
    WM_CLOSE = 0x0010
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Встраивание Windows Terminal доступно только в Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        self._enum_callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        self.user32.EnumWindows.argtypes = [self._enum_callback_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        self.user32.SetParent.restype = wintypes.HWND
        self.user32.MoveWindow.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.BOOL,
        ]
        self.user32.MoveWindow.restype = wintypes.BOOL
        self.user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self.user32.SetWindowPos.restype = wintypes.BOOL
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.ShowWindow.restype = wintypes.BOOL
        self.user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.PostMessageW.restype = wintypes.BOOL
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self._get_window_long = self.user32.GetWindowLongPtrW
            self._set_window_long = self.user32.SetWindowLongPtrW
            value_type = ctypes.c_ssize_t
        else:  # pragma: no cover - 32-bit Windows build
            self._get_window_long = self.user32.GetWindowLongW
            self._set_window_long = self.user32.SetWindowLongW
            value_type = ctypes.c_long
        self._get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
        self._get_window_long.restype = value_type
        self._set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, value_type]
        self._set_window_long.restype = value_type

    def terminal_windows(self) -> set[int]:
        result: set[int] = set()

        @self._enum_callback_type
        def collect(hwnd: int, _lparam: int) -> bool:
            if self.user32.IsWindowVisible(hwnd) and self._is_windows_terminal_window(hwnd):
                result.add(int(hwnd))
            return True

        if not self.user32.EnumWindows(collect, 0):
            error = ctypes.get_last_error()
            if error:
                raise OSError(error, "Не удалось перечислить окна Windows")
        return result

    def _is_windows_terminal_window(self, hwnd: int) -> bool:
        process_name = self._process_name(hwnd)
        if process_name in {
            "windowsterminal.exe",
            "windowsterminalpreview.exe",
            "windowsterminalcanary.exe",
        }:
            return True
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buffer, len(buffer))
        return "cascadia" in buffer.value.casefold()

    def _process_name(self, hwnd: int) -> str:
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return ""
        handle = self.kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value
        )
        if not handle:
            return ""
        try:
            capacity = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            if not self.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(capacity)
            ):
                return ""
            return os.path.basename(buffer.value).casefold()
        finally:
            self.kernel32.CloseHandle(handle)

    def exists(self, hwnd: int | None) -> bool:
        return bool(hwnd and self.user32.IsWindow(hwnd))

    def attach(self, child: int, parent: int, width: int, height: int) -> int:
        original_style = int(self._get_window_long(child, self.GWL_STYLE))
        embedded_style = original_style
        embedded_style &= ~(
            self.WS_POPUP
            | self.WS_CAPTION
            | self.WS_THICKFRAME
            | self.WS_MINIMIZEBOX
            | self.WS_MAXIMIZEBOX
            | self.WS_SYSMENU
        )
        embedded_style |= self.WS_CHILD
        self._set_window_long(child, self.GWL_STYLE, embedded_style)
        ctypes.set_last_error(0)
        previous_parent = self.user32.SetParent(child, parent)
        error = ctypes.get_last_error()
        if not previous_parent and error:
            self._set_window_long(child, self.GWL_STYLE, original_style)
            raise OSError(error, "Windows не разрешила встроить окно Terminal")
        self.user32.SetWindowPos(
            child,
            0,
            0,
            0,
            max(1, width),
            max(1, height),
            self.SWP_NOZORDER | self.SWP_NOACTIVATE | self.SWP_FRAMECHANGED,
        )
        self.user32.ShowWindow(child, self.SW_SHOW)
        return original_style

    def resize(self, hwnd: int, width: int, height: int) -> None:
        if self.exists(hwnd):
            self.user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                max(1, width),
                max(1, height),
                self.SWP_NOZORDER | self.SWP_NOACTIVATE | self.SWP_SHOWWINDOW,
            )

    def request_close(self, hwnd: int) -> None:
        if self.exists(hwnd) and not self.user32.PostMessageW(hwnd, self.WM_CLOSE, 0, 0):
            error = ctypes.get_last_error()
            raise OSError(error, "Не удалось закрыть окно Windows Terminal")

    def detach(
        self,
        hwnd: int,
        original_style: int,
        position: QPoint,
        width: int,
        height: int,
    ) -> None:
        if not self.exists(hwnd):
            return
        ctypes.set_last_error(0)
        self.user32.SetParent(hwnd, 0)
        error = ctypes.get_last_error()
        if error:
            raise OSError(error, "Не удалось отделить окно Terminal")
        self._set_window_long(hwnd, self.GWL_STYLE, original_style)
        self.user32.SetWindowPos(
            hwnd,
            0,
            position.x(),
            position.y(),
            max(640, width),
            max(420, height),
            self.SWP_NOZORDER | self.SWP_FRAMECHANGED | self.SWP_SHOWWINDOW,
        )


class _TerminalSurface(QWidget):
    def __init__(self, resize_callback: Callable[[], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._resize_callback = resize_callback
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setObjectName("terminalSurface")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._resize_callback()


class EmbeddedWindowsTerminalHost(QFrame):
    """Hosts one real Windows Terminal window inside a Qt widget."""

    status_changed = Signal(str)
    embedding_changed = Signal(bool)

    discovery_timeout_seconds = 10.0

    def __init__(
        self,
        launcher: WindowsTerminalLauncher,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.launcher = launcher
        self.window_name = f"winsshui-embedded-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._api: _Win32WindowApi | None
        try:
            self._api = _Win32WindowApi()
        except OSError:
            self._api = None
        self._terminal_hwnd: int | None = None
        self._original_style: int | None = None
        self._windows_before_launch: set[int] = set()
        self._discovery_started = 0.0
        self._pending = False
        self._external_only = False

        self.setObjectName("embeddedTerminalCard")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        self.state_label = QLabel("Windows Terminal ещё не запущен")
        self.state_label.setObjectName("secondary")
        toolbar.addWidget(self.state_label)
        toolbar.addStretch()
        self.detach_button = QPushButton("Открыть отдельно")
        self.detach_button.setEnabled(False)
        self.detach_button.clicked.connect(self.detach_to_desktop)
        toolbar.addWidget(self.detach_button)
        root.addLayout(toolbar)

        stack_container = QWidget()
        self._stack = QStackedLayout(stack_container)
        self._stack.setContentsMargins(0, 0, 0, 0)
        placeholder = QFrame()
        placeholder.setObjectName("terminalPlaceholder")
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.addStretch()
        placeholder_title = QLabel("Встроенный Windows Terminal")
        placeholder_title.setObjectName("detailsTitle")
        placeholder_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_text = QLabel(
            "Откройте SSH-подключение — настоящее окно Windows Terminal появится здесь.\n"
            "Режим экспериментальный: при невозможности встраивания окно останется отдельным."
        )
        placeholder_text.setObjectName("secondary")
        placeholder_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_text.setWordWrap(True)
        placeholder_layout.addWidget(placeholder_title)
        placeholder_layout.addWidget(placeholder_text)
        placeholder_layout.addStretch()
        self.surface = _TerminalSurface(self._resize_terminal, stack_container)
        self._stack.addWidget(placeholder)
        self._stack.addWidget(self.surface)
        root.addWidget(stack_container, 1)

        self._discovery_timer = QTimer(self)
        self._discovery_timer.setInterval(120)
        self._discovery_timer.timeout.connect(self._discover_window)
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(1000)
        self._monitor_timer.timeout.connect(self._monitor_window)

    @property
    def available(self) -> bool:
        return self._api is not None

    @property
    def is_embedded(self) -> bool:
        return bool(self._api and self._api.exists(self._terminal_hwnd))

    def launch_connection(
        self,
        host: SshHost,
        mode: TerminalLaunchMode,
        credential_alias: str | None = None,
    ) -> bool | None:
        return self._launch(
            lambda: self.launcher.launch(
                host, mode, credential_alias, window_name=self.window_name
            )
        )

    def launch_workspace(
        self,
        items: list[tuple[SshHost, WorkspaceItem | TerminalLaunchMode]],
    ) -> bool | None:
        return self._launch(
            lambda: self.launcher.launch_workspace(items, self.window_name)
        )

    def launch_snippet(
        self,
        host: SshHost,
        remote_command: str,
        title: str | None,
        credential_alias: str | None,
    ) -> bool | None:
        return self._launch(
            lambda: self.launcher.launch_snippet(
                host,
                remote_command,
                title,
                credential_alias,
                window_name=self.window_name,
            )
        )

    def _launch(self, launch_action: Callable[[], object]) -> bool | None:
        api = self._api
        if api is None:
            return None
        if self._external_only:
            launch_action()
            return False
        if self._terminal_hwnd is not None and not api.exists(self._terminal_hwnd):
            self._forget_window("Предыдущее окно Windows Terminal закрыто")
        if not self.is_embedded and not self._pending:
            self._windows_before_launch = api.terminal_windows()
            self._discovery_started = time.monotonic()
            self._pending = True
            self.state_label.setText("Запускаю и встраиваю Windows Terminal…")
            self._discovery_timer.start()
        try:
            launch_action()
        except Exception:
            if self._pending and not self.is_embedded:
                self._pending = False
                self._discovery_timer.stop()
            raise
        return True

    def _discover_window(self) -> None:
        api = self._api
        if api is None:
            self._discovery_timer.stop()
            return
        try:
            candidates = api.terminal_windows() - self._windows_before_launch
        except OSError as exception:
            self._embedding_failed(
                f"Windows Terminal открыт отдельно: {exception}"
            )
            return
        if candidates:
            hwnd = max(candidates)
            try:
                native_width, native_height = self._native_surface_size()
                original_style = api.attach(
                    hwnd,
                    int(self.surface.winId()),
                    native_width,
                    native_height,
                )
            except OSError as exception:
                self._embedding_failed(
                    f"Windows Terminal открыт отдельно: {exception}"
                )
                return
            self._terminal_hwnd = hwnd
            self._original_style = original_style
            self._pending = False
            self._discovery_timer.stop()
            self._stack.setCurrentWidget(self.surface)
            self.detach_button.setEnabled(True)
            self.state_label.setText("Windows Terminal встроен · экспериментальный режим")
            self._monitor_timer.start()
            self.embedding_changed.emit(True)
            self.status_changed.emit("Windows Terminal встроен в WinSSH UI")
            for delay in (0, 100, 300, 700, 1500, 3000):
                QTimer.singleShot(delay, self._resize_terminal)
            return
        if time.monotonic() - self._discovery_started >= self.discovery_timeout_seconds:
            self._embedding_failed(
                "Не удалось найти окно Windows Terminal; оно оставлено отдельным"
            )

    def _embedding_failed(self, message: str) -> None:
        self._pending = False
        self._external_only = True
        self._discovery_timer.stop()
        self.state_label.setText(message)
        self.status_changed.emit(message)
        self.embedding_changed.emit(False)

    def _monitor_window(self) -> None:
        if self._api is None:
            return
        if not self._api.exists(self._terminal_hwnd):
            self._forget_window("Окно Windows Terminal закрыто")
            return
        self._resize_terminal()

    def _resize_terminal(self) -> None:
        if self._api is not None and self._terminal_hwnd is not None:
            width, height = self._native_surface_size()
            self._api.resize(self._terminal_hwnd, width, height)

    def _native_surface_size(self) -> tuple[int, int]:
        scale = max(1.0, self.surface.devicePixelRatioF())
        return (
            max(1, round(self.surface.width() * scale)),
            max(1, round(self.surface.height() * scale)),
        )

    def detach_to_desktop(self) -> None:
        api = self._api
        hwnd = self._terminal_hwnd
        style = self._original_style
        if self._pending and (hwnd is None or style is None):
            self._embedding_failed("Windows Terminal открыт в отдельном окне")
            return
        if api is None or hwnd is None or style is None:
            return
        scale = max(1.0, self.surface.devicePixelRatioF())
        logical_position = self.surface.mapToGlobal(QPoint(24, 24))
        position = QPoint(
            round(logical_position.x() * scale),
            round(logical_position.y() * scale),
        )
        width, height = self._native_surface_size()
        try:
            api.detach(hwnd, style, position, width, height)
        except OSError as exception:
            self.status_changed.emit(str(exception))
            return
        self._forget_window("Windows Terminal открыт в отдельном окне")
        self._external_only = True
        self.status_changed.emit("Windows Terminal отделён от WinSSH UI")

    def close_terminal(self) -> None:
        api = self._api
        hwnd = self._terminal_hwnd
        self._pending = False
        self._discovery_timer.stop()
        self._monitor_timer.stop()
        if api is None or hwnd is None:
            return
        try:
            api.request_close(hwnd)
        except OSError as exception:
            self.status_changed.emit(str(exception))
        self._terminal_hwnd = None
        self._original_style = None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._resize_terminal)

    def _forget_window(self, message: str) -> None:
        was_embedded = self._terminal_hwnd is not None
        self._terminal_hwnd = None
        self._original_style = None
        self._pending = False
        self._external_only = False
        self._discovery_timer.stop()
        self._monitor_timer.stop()
        self._stack.setCurrentIndex(0)
        self.detach_button.setEnabled(False)
        self.state_label.setText(message)
        if was_embedded:
            self.embedding_changed.emit(False)

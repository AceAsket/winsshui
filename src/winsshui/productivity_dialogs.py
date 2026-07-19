from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from winsshui.device_icons import DEVICE_ICON_OPTIONS, device_icon, resolve_device_icon
from winsshui.models import ConnectionItem, TerminalLaunchMode


class QuickLaunchDialog(QDialog):
    def __init__(
        self,
        connections: list[ConnectionItem],
        open_terminal: Callable[[ConnectionItem, TerminalLaunchMode], None],
        open_sftp: Callable[[ConnectionItem], None],
        open_winscp: Callable[[ConnectionItem], None],
        toggle_tunnel: Callable[[ConnectionItem], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.connections = connections
        self.open_terminal = open_terminal
        self.open_sftp = open_sftp
        self.open_winscp = open_winscp
        self.toggle_tunnel = toggle_tunnel
        self.setWindowTitle("Быстрое подключение — Ctrl+K")
        self.resize(680, 520)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Алиас, адрес, папка, тег или заметка…")
        self.search.textChanged.connect(self._reload)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self._run("terminal"))
        layout.addWidget(self.list, 1)
        hint = QLabel("Enter — терминал · Ctrl+Enter — split · Alt+S — SFTP/SCP")
        hint.setObjectName("secondary")
        layout.addWidget(hint)
        actions = QHBoxLayout()
        terminal = QPushButton("Терминал")
        terminal.clicked.connect(lambda: self._run("terminal"))
        split = QPushButton("Split справа")
        split.clicked.connect(lambda: self._run("split"))
        sftp = QPushButton("SFTP / SCP")
        sftp.clicked.connect(lambda: self._run("sftp"))
        winscp = QPushButton("WinSCP")
        winscp.clicked.connect(lambda: self._run("winscp"))
        tunnel = QPushButton("Туннели")
        tunnel.clicked.connect(lambda: self._run("tunnel"))
        for button in (terminal, split, sftp, winscp, tunnel):
            actions.addWidget(button)
        layout.addLayout(actions)
        self._reload()
        self.search.setFocus()

    def _reload(self) -> None:
        query = self.search.text().strip().casefold()
        self.list.clear()
        for connection in sorted(
            self.connections,
            key=lambda item: (not item.is_favorite, item.alias.casefold()),
        ):
            haystack = " ".join(
                (
                    connection.alias,
                    connection.host.display_endpoint,
                    connection.group_name or "",
                    connection.notes or "",
                    " ".join(connection.tags),
                )
            ).casefold()
            if query and query not in haystack:
                continue
            item = QListWidgetItem(
                device_icon(
                    resolve_device_icon(
                        connection.icon_name,
                        connection.alias,
                        connection.host.hostname,
                        connection.group_name,
                    )
                ),
                f"{connection.alias}\n{connection.host.display_endpoint}  ·  {connection.group_display}",
            )
            item.setData(Qt.ItemDataRole.UserRole, connection)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _selected(self) -> ConnectionItem | None:
        item = self.list.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return value if isinstance(value, ConnectionItem) else None

    def _run(self, action: str) -> None:
        connection = self._selected()
        if not connection:
            return
        self.accept()
        if action == "terminal":
            self.open_terminal(connection, TerminalLaunchMode.NEW_TAB)
        elif action == "split":
            self.open_terminal(connection, TerminalLaunchMode.SPLIT_RIGHT)
        elif action == "sftp":
            self.open_sftp(connection)
        elif action == "winscp":
            self.open_winscp(connection)
        else:
            self.toggle_tunnel(connection)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._run("split" if event.modifiers() & Qt.KeyboardModifier.ControlModifier else "terminal")
            return
        if event.key() == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._run("sftp")
            return
        super().keyPressEvent(event)


class BulkActionsDialog(QDialog):
    def __init__(
        self,
        connections: list[ConnectionItem],
        initially_selected: set[str] | None,
        apply_metadata: Callable[[list[ConnectionItem], str | None, tuple[str, ...], str | None], None],
        check_connections: Callable[[list[ConnectionItem]], None],
        start_tunnels: Callable[[list[ConnectionItem]], None],
        open_workspace: Callable[[list[ConnectionItem]], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.connections = connections
        self.apply_metadata = apply_metadata
        self.check_connections = check_connections
        self.start_tunnels = start_tunnels
        self.open_workspace = open_workspace
        selected_keys = {alias.casefold() for alias in (initially_selected or set())}
        self.setWindowTitle("Массовые действия")
        self.resize(760, 600)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(connections), 3)
        self.table.setHorizontalHeaderLabels(["Выбрать", "Подключение", "Папка / теги"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().ResizeMode.Stretch)
        for row, connection in enumerate(connections):
            checked = QTableWidgetItem()
            checked.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checked.setCheckState(
                Qt.CheckState.Checked
                if not selected_keys or connection.alias.casefold() in selected_keys
                else Qt.CheckState.Unchecked
            )
            checked.setData(Qt.ItemDataRole.UserRole, connection)
            self.table.setItem(row, 0, checked)
            self.table.setItem(row, 1, QTableWidgetItem(connection.alias))
            self.table.setItem(
                row, 2, QTableWidgetItem(f"{connection.group_display} · {', '.join(connection.tags)}")
            )
        layout.addWidget(self.table, 1)
        edit_row = QHBoxLayout()
        self.change_group = QCheckBox("Заменить папку")
        self.group_edit = QLineEdit()
        self.group_edit.setPlaceholderText("Production/Web")
        self.add_tags = QCheckBox("Добавить теги")
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("critical, linux")
        self.change_icon = QCheckBox("Иконка")
        self.icon_combo = QComboBox()
        self.icon_combo.addItem("Автоматически", None)
        for name, label in DEVICE_ICON_OPTIONS:
            self.icon_combo.addItem(device_icon(name), label, name)
        for widget in (
            self.change_group,
            self.group_edit,
            self.add_tags,
            self.tags_edit,
            self.change_icon,
            self.icon_combo,
        ):
            edit_row.addWidget(widget)
        layout.addLayout(edit_row)
        actions = QHBoxLayout()
        apply_button = QPushButton("Применить метаданные")
        apply_button.clicked.connect(self._apply)
        check_button = QPushButton("Проверить подключения")
        check_button.clicked.connect(lambda: self._dispatch(self.check_connections))
        tunnels_button = QPushButton("Запустить туннели")
        tunnels_button.clicked.connect(lambda: self._dispatch(self.start_tunnels))
        workspace_button = QPushButton("Открыть в Terminal")
        workspace_button.clicked.connect(lambda: self._dispatch(self.open_workspace))
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        for button in (apply_button, check_button, tunnels_button, workspace_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)

    def selected_connections(self) -> list[ConnectionItem]:
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            value = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked and isinstance(value, ConnectionItem):
                result.append(value)
        return result

    def _apply(self) -> None:
        group = self.group_edit.text().strip() if self.change_group.isChecked() else None
        tags = tuple(
            part.strip() for part in self.tags_edit.text().replace(";", ",").split(",") if part.strip()
        ) if self.add_tags.isChecked() else ()
        icon = self.icon_combo.currentData() if self.change_icon.isChecked() else None
        self.apply_metadata(
            self.selected_connections(), group, tags, icon if isinstance(icon, str) else None
        )

    def _dispatch(self, callback: Callable[[list[ConnectionItem]], None]) -> None:
        selected = self.selected_connections()
        if selected:
            self.accept()
            callback(selected)

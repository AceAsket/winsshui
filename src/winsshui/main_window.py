from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from winsshui.catalog import ConnectionCatalog
from winsshui.dialogs import ImportConnectionsDialog, NewConnectionDialog
from winsshui.importers import WindowsClientImporter
from winsshui.models import (
    ConnectionItem,
    ConnectionMetadata,
    EffectiveSshConfiguration,
    TerminalLaunchMode,
)
from winsshui.ssh_config import SshConfigReader, SshConfigurationResolver
from winsshui.ssh_writer import SshConfigWriter
from winsshui.terminal import WindowsTerminalLauncher, detect_tools


class MainWindow(QMainWindow):
    def __init__(self, app_data_directory: Path) -> None:
        super().__init__()
        self.setWindowTitle("WinSSH UI")
        self.resize(1120, 760)
        self.setMinimumSize(860, 600)

        self.config_path = Path.home() / ".ssh" / "config"
        self.catalog = ConnectionCatalog(app_data_directory / "catalog.db")
        self.config_reader = SshConfigReader()
        self.configuration_resolver = SshConfigurationResolver()
        self.config_writer = SshConfigWriter(self.config_reader)
        self.client_importer = WindowsClientImporter()
        self.terminal_launcher = WindowsTerminalLauncher()
        self.tools = detect_tools()
        self.connections: list[ConnectionItem] = []
        self._resolve_process: QProcess | None = None
        self._resolved_alias: str | None = None

        self._build_ui()
        self._apply_style()

        try:
            self.catalog.initialize()
            self.reload_connections()
        except Exception as exception:
            self._show_error("Не удалось открыть локальный каталог", exception)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        title = QLabel("SSH Connections")
        title.setObjectName("title")
        subtitle = QLabel("Подключения из OpenSSH config")
        subtitle.setObjectName("secondary")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        self.new_button = QPushButton("＋  Новое подключение")
        self.new_button.setObjectName("accentButton")
        self.new_button.clicked.connect(self._create_connection)
        header.addWidget(self.new_button)
        self.import_button = QPushButton("Импорт")
        self.import_button.clicked.connect(self._import_connections)
        header.addWidget(self.import_button)
        self.refresh_button = QPushButton("↻  Обновить")
        self.refresh_button.clicked.connect(self.reload_connections)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по имени, адресу, пользователю или группе")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self._rebuild_connection_list())
        root.addWidget(self.search_edit)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_details_panel())
        splitter.setSizes([420, 650])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("secondary")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tool_status_label = QLabel(self.tools.message)
        self.tool_status_label.setObjectName("secondary")
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.tool_status_label)
        root.addLayout(footer)

        self.setCentralWidget(central)

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        connection_heading = QLabel("Подключения")
        connection_heading.setObjectName("sectionTitle")
        layout.addWidget(connection_heading)

        self.connection_list = QTreeWidget()
        self.connection_list.setHeaderHidden(True)
        self.connection_list.setRootIsDecorated(True)
        self.connection_list.setIndentation(18)
        self.connection_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.connection_list.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.connection_list, 1)

        history_heading = QLabel("Недавние подключения")
        history_heading.setObjectName("sectionTitle")
        layout.addWidget(history_heading)

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(150)
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.history_list)
        return panel

    def _build_details_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)

        self.alias_label = QLabel("Выберите подключение")
        self.alias_label.setObjectName("detailsTitle")
        self.endpoint_label = QLabel("Слева появятся хосты из ~/.ssh/config")
        self.endpoint_label.setObjectName("secondary")
        self.endpoint_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.alias_label)
        layout.addWidget(self.endpoint_label)

        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(12)
        self.identity_label = self._selectable_label("Определяется OpenSSH")
        self.proxy_label = self._selectable_label("Нет")
        self.config_label = self._selectable_label(str(self.config_path))
        form.addRow("Ключ", self.identity_label)
        form.addRow("ProxyJump", self.proxy_label)
        form.addRow("Config", self.config_label)
        layout.addLayout(form)

        organization = QLabel("Папка")
        organization.setObjectName("sectionTitle")
        layout.addWidget(organization)

        self.favorite_button = QPushButton("☆  Добавить в избранное")
        self.favorite_button.setCheckable(True)
        self.favorite_button.clicked.connect(self._toggle_favorite)
        layout.addWidget(self.favorite_button)

        group_row = QHBoxLayout()
        self.group_edit = QLineEdit()
        self.group_edit.setPlaceholderText("Папка, например Production/Web")
        self.save_group_button = QPushButton("Сохранить папку")
        self.save_group_button.clicked.connect(self._save_group)
        group_row.addWidget(self.group_edit, 1)
        group_row.addWidget(self.save_group_button)
        layout.addLayout(group_row)
        layout.addStretch()

        actions = QHBoxLayout()
        self.connect_button = QPushButton("Открыть во вкладке")
        self.connect_button.setObjectName("accentButton")
        self.connect_button.clicked.connect(lambda: self._launch(TerminalLaunchMode.NEW_TAB))
        self.split_button = QPushButton("Открыть справа")
        self.split_button.clicked.connect(lambda: self._launch(TerminalLaunchMode.SPLIT_RIGHT))
        actions.addWidget(self.connect_button)
        actions.addWidget(self.split_button)
        actions.addStretch()
        layout.addLayout(actions)

        self._set_details_enabled(False)
        return panel

    @staticmethod
    def _selectable_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _apply_style(self) -> None:
        QApplication.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #202020; color: #f5f5f5; }
            QLabel#title { font-size: 25px; font-weight: 600; }
            QLabel#detailsTitle { font-size: 20px; font-weight: 600; }
            QLabel#sectionTitle { font-size: 14px; font-weight: 600; }
            QLabel#secondary { color: #b8b8b8; }
            QFrame#card { background: #2b2b2b; border: 1px solid #3b3b3b; border-radius: 9px; }
            QLineEdit { background: #303030; border: 1px solid #505050; border-radius: 6px; padding: 8px 10px; }
            QLineEdit:focus { border-color: #60a5fa; }
            QPushButton { background: #383838; border: 1px solid #505050; border-radius: 6px; padding: 8px 14px; }
            QPushButton:hover { background: #444444; }
            QPushButton:disabled { color: #777777; background: #303030; }
            QPushButton#accentButton { background: #2563eb; border-color: #3b82f6; color: white; }
            QPushButton#accentButton:hover { background: #1d4ed8; }
            QListWidget, QTreeWidget { background: transparent; border: none; outline: none; }
            QListWidget::item, QTreeWidget::item { border-radius: 6px; padding: 7px; margin: 1px; }
            QListWidget::item:selected, QTreeWidget::item:selected { background: #164e8a; }
            QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected { background: #343434; }
            QSplitter::handle { background: transparent; width: 14px; }
            """
        )

    def reload_connections(self) -> None:
        selected_alias = self._selected_connection().alias if self._selected_connection() else None
        try:
            metadata = self.catalog.get_all_metadata()
            self.connections = [
                ConnectionItem(
                    host,
                    metadata.get(host.alias.casefold(), None).is_favorite
                    if host.alias.casefold() in metadata
                    else False,
                    metadata.get(host.alias.casefold(), None).group_name
                    if host.alias.casefold() in metadata
                    else None,
                )
                for host in self.config_reader.read(self.config_path)
            ]
            self._rebuild_connection_list(selected_alias)
            self._reload_history()
            self.status_label.setText(f"Загружено подключений: {len(self.connections)}")
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось прочитать SSH config", exception)

    def _create_connection(self) -> None:
        dialog = NewConnectionDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft = dialog.draft()
        try:
            result = self.config_writer.append(self.config_path, draft)
            if not result.added:
                QMessageBox.information(
                    self,
                    "Алиас уже существует",
                    f"Host {draft.alias} уже есть в SSH config. Выберите другой алиас.",
                )
                return
            self.catalog.save_metadata(
                ConnectionMetadata(draft.alias, draft.is_favorite, draft.group_name)
            )
            self.reload_connections()
            self._rebuild_connection_list(draft.alias)
            self.status_label.setText(f"Подключение {draft.alias} сохранено в {self.config_path}")
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось сохранить подключение", exception)

    def _import_connections(self) -> None:
        dialog = ImportConnectionsDialog(self.client_importer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        candidates = dialog.selected_candidates()
        drafts = [candidate.to_draft() for candidate in candidates]
        try:
            result = self.config_writer.append_many(self.config_path, drafts)
            for draft in result.added:
                self.catalog.save_metadata(
                    ConnectionMetadata(draft.alias, draft.is_favorite, draft.group_name)
                )
            self.reload_connections()
            message = f"Импортировано подключений: {len(result.added)}"
            if result.skipped_aliases:
                message += f"; пропущены существующие алиасы: {', '.join(result.skipped_aliases)}"
            self.status_label.setText(message)
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось импортировать подключения", exception)

    def _rebuild_connection_list(self, selected_alias: str | None = None) -> None:
        if isinstance(selected_alias, str):
            alias_to_restore = selected_alias
        else:
            selected = self._selected_connection()
            alias_to_restore = selected.alias if selected else None
        search = self.search_edit.text().strip().casefold()
        filtered = [
            connection
            for connection in self.connections
            if not search
            or search in connection.alias.casefold()
            or search in connection.host.display_endpoint.casefold()
            or search in connection.group_display.casefold()
        ]
        filtered.sort(
            key=lambda connection: (
                not connection.is_favorite,
                not bool(connection.group_name),
                (connection.group_name or "").casefold(),
                connection.alias.casefold(),
            )
        )

        self.connection_list.blockSignals(True)
        self.connection_list.clear()
        selected_item: QTreeWidgetItem | None = None
        first_connection_item: QTreeWidgetItem | None = None
        folder_items: dict[str, QTreeWidgetItem] = {}
        root = self.connection_list.invisibleRootItem()

        def folder_parent(folder_path: str | None) -> QTreeWidgetItem:
            parent = root
            accumulated: list[str] = []
            normalized_path = (folder_path or "").replace("\\", "/").strip("/ ")
            for part in (part.strip() for part in normalized_path.split("/") if part.strip()):
                accumulated.append(part)
                key = "/".join(accumulated).casefold()
                folder_item = folder_items.get(key)
                if folder_item is None:
                    folder_item = QTreeWidgetItem([f"📁  {part}"])
                    folder_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    parent.addChild(folder_item)
                    folder_items[key] = folder_item
                parent = folder_item
            return parent

        for connection in filtered:
            star = "★" if connection.is_favorite else "☆"
            item = QTreeWidgetItem(
                [f"{star}  {connection.alias}\n     {connection.host.display_endpoint}"]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, connection)
            item.setToolTip(0, connection.host.display_endpoint)
            folder_parent(connection.group_name).addChild(item)
            first_connection_item = first_connection_item or item
            if connection.alias.casefold() == (alias_to_restore or "").casefold():
                selected_item = item
        self.connection_list.expandAll()
        self.connection_list.blockSignals(False)
        if selected_item is not None:
            self.connection_list.setCurrentItem(selected_item)
        elif first_connection_item is not None and alias_to_restore is None:
            self.connection_list.setCurrentItem(first_connection_item)
        else:
            self._selection_changed(None, None)

    def _reload_history(self) -> None:
        self.history_list.clear()
        for entry in self.catalog.get_recent():
            self.history_list.addItem(f"{entry.alias}    ·    {entry.local_timestamp}")

    def _selected_connection(self) -> ConnectionItem | None:
        item = self.connection_list.currentItem()
        connection = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return connection if isinstance(connection, ConnectionItem) else None

    def _selection_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        connection = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if not isinstance(connection, ConnectionItem):
            self._set_details_enabled(False)
            self.alias_label.setText("Выберите подключение")
            self.endpoint_label.setText("Слева появятся хосты из ~/.ssh/config")
            self.identity_label.setText("Определяется OpenSSH")
            self.proxy_label.setText("Нет")
            return

        self._set_details_enabled(True)
        self.alias_label.setText(connection.alias)
        self.endpoint_label.setText("Получаю эффективную конфигурацию…")
        self.identity_label.setText(connection.host.identity_file or "Определяется OpenSSH")
        self.proxy_label.setText(connection.host.proxy_jump or "Нет")
        self.group_edit.setText(connection.group_name or "")
        self.favorite_button.setChecked(connection.is_favorite)
        self.favorite_button.setText(
            "★  Удалить из избранного" if connection.is_favorite else "☆  Добавить в избранное"
        )
        self._resolve_effective_configuration(connection)

    def _set_details_enabled(self, has_selection: bool) -> None:
        can_connect = has_selection and self.tools.can_connect
        self.connect_button.setEnabled(can_connect)
        self.split_button.setEnabled(can_connect)
        self.favorite_button.setEnabled(has_selection)
        self.group_edit.setEnabled(has_selection)
        self.save_group_button.setEnabled(has_selection)

    def _resolve_effective_configuration(self, connection: ConnectionItem) -> None:
        if not self.tools.ssh_path:
            self.endpoint_label.setText("OpenSSH Client не найден")
            return

        if self._resolve_process and self._resolve_process.state() != QProcess.ProcessState.NotRunning:
            self._resolve_process.kill()

        process = QProcess(self)
        self._resolve_process = process
        self._resolved_alias = connection.alias
        process.setProgram(self.tools.ssh_path)
        process.setArguments(["-G", "--", connection.alias])

        timer = QTimer(process)
        timer.setSingleShot(True)
        timer.timeout.connect(process.kill)
        process.finished.connect(
            lambda exit_code, _status: self._resolution_finished(process, connection.alias, exit_code, timer)
        )
        process.start()
        timer.start(5000)

    def _resolution_finished(
        self,
        process: QProcess,
        alias: str,
        exit_code: int,
        timer: QTimer,
    ) -> None:
        if not isValid(process):
            return
        if isValid(timer):
            timer.stop()
        if process is not self._resolve_process or alias != self._resolved_alias:
            process.deleteLater()
            return
        output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        error = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        process.deleteLater()
        self._resolve_process = None
        if exit_code != 0:
            self.endpoint_label.setText("Не удалось получить эффективную конфигурацию")
            self.status_label.setText(error or "ssh -G завершился с ошибкой")
            return
        configuration = self.configuration_resolver.parse(alias, output.splitlines())
        self._show_effective_configuration(configuration)

    def closeEvent(self, event: QCloseEvent) -> None:
        process = self._resolve_process
        self._resolve_process = None
        self._resolved_alias = None
        if process is not None and isValid(process):
            try:
                process.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(500)
        super().closeEvent(event)

    def _show_effective_configuration(self, configuration: EffectiveSshConfiguration) -> None:
        if self._selected_connection() and self._selected_connection().alias == configuration.alias:
            self.endpoint_label.setText(configuration.endpoint)
            self.identity_label.setText(configuration.identity_file)
            self.proxy_label.setText(configuration.proxy_jump or "Нет")

    def _toggle_favorite(self, checked: bool) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        connection.is_favorite = checked
        try:
            self.catalog.save_metadata(connection.metadata())
            self.status_label.setText(
                f"{connection.alias} {'добавлен в' if checked else 'удалён из'} избранного"
            )
            self._rebuild_connection_list(connection.alias)
        except sqlite3.Error as exception:  # type: ignore[name-defined]
            connection.is_favorite = not checked
            self._show_error("Не удалось сохранить избранное", exception)

    def _save_group(self) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        previous_group = connection.group_name
        connection.group_name = self.group_edit.text().strip() or None
        try:
            self.catalog.save_metadata(connection.metadata())
            self.status_label.setText(f"Папка для {connection.alias} сохранена")
            self._rebuild_connection_list(connection.alias)
        except Exception as exception:
            connection.group_name = previous_group
            self._show_error("Не удалось сохранить группу", exception)

    def _launch(self, mode: TerminalLaunchMode) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        try:
            self.terminal_launcher.launch(connection.host, mode)
            self.catalog.record_launch(connection.alias, mode)
            self._reload_history()
            self.status_label.setText(f"Открываю {connection.alias} в Windows Terminal…")
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось запустить Windows Terminal", exception)

    def _show_error(self, title: str, exception: Exception) -> None:
        self.status_label.setText(f"{title}: {exception}")
        QMessageBox.critical(self, title, str(exception))

from __future__ import annotations

import sqlite3
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QPoint, QProcess, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QFont
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from winsshui import __version__
from winsshui.backup import BackupManager
from winsshui.catalog import ConnectionCatalog
from winsshui.dialogs import (
    CommandSnippetsDialog,
    DiagnosticsDialog,
    ImportConnectionsDialog,
    NewConnectionDialog,
    SshKeyManagerDialog,
    WorkspaceDialog,
)
from winsshui.diagnostics import SshDiagnostics
from winsshui.device_icons import (
    DEVICE_ICON_OPTIONS,
    device_icon,
    folder_icon,
    resolve_device_icon,
)
from winsshui.host_keys import KnownHostsManager
from winsshui.importers import ImportCandidate, WindowsClientImporter, connection_fingerprint
from winsshui.models import (
    CommandSnippet,
    ConnectionItem,
    ConnectionMetadata,
    EffectiveSshConfiguration,
    TerminalLaunchMode,
)
from winsshui.resources import resource_path
from winsshui.ssh_config import SshConfigReader, SshConfigurationResolver
from winsshui.ssh_keys import SshKeyManager
from winsshui.ssh_writer import SshConfigWriter
from winsshui.ssh_writer import SshConnectionDraft
from winsshui.terminal import (
    ManagedTunnelCommand,
    WindowsTerminalLauncher,
    WinScpLauncher,
    detect_tools,
)
from winsshui.updates import LATEST_RELEASE_API, is_newer_version, parse_latest_release


class MainWindow(QMainWindow):
    def __init__(self, app_data_directory: Path) -> None:
        super().__init__()
        self.setWindowTitle("WinSSH UI")
        self.resize(1120, 760)
        self.setMinimumSize(980, 640)

        self.config_path = Path.home() / ".ssh" / "config"
        self.app_data_directory = app_data_directory.resolve()
        self.catalog = ConnectionCatalog(app_data_directory / "catalog.db")
        self.backup_manager = BackupManager(
            Path.home() / ".ssh",
            self.config_path,
            self.catalog.database_path,
        )
        self.config_reader = SshConfigReader()
        self.configuration_resolver = SshConfigurationResolver()
        self.config_writer = SshConfigWriter(self.config_reader)
        self.client_importer = WindowsClientImporter()
        self.terminal_launcher = WindowsTerminalLauncher()
        self.winscp_launcher = WinScpLauncher()
        self.host_key_manager = KnownHostsManager(Path.home() / ".ssh" / "known_hosts")
        self.tools = detect_tools()
        self.key_manager = SshKeyManager(
            Path.home() / ".ssh",
            terminal_path=self.tools.terminal_path,
        )
        self.ssh_diagnostics = SshDiagnostics(self.tools.ssh_path)
        self.connections: list[ConnectionItem] = []
        self._resolve_process: QProcess | None = None
        self._resolved_alias: str | None = None
        self._effective_configuration: EffectiveSshConfiguration | None = None
        self._tunnel_processes: dict[str, QProcess] = {}
        self._stopping_tunnels: set[str] = set()
        self._update_manager = QNetworkAccessManager(self)
        self._update_reply: QNetworkReply | None = None

        self._build_ui()
        self._apply_style()

        try:
            self.catalog.initialize()
            self.reload_connections()
            QTimer.singleShot(1500, self._auto_check_updates)
        except Exception as exception:
            self._show_error("Не удалось открыть локальный каталог", exception)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("appRoot")
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        title = QLabel("WinSSH UI")
        title.setObjectName("title")
        subtitle = QLabel("Менеджер подключений OpenSSH")
        subtitle.setObjectName("secondary")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        self.new_button = QPushButton("＋  Подключение")
        self.new_button.setObjectName("accentButton")
        self.new_button.clicked.connect(self._create_connection)
        header.addWidget(self.new_button)
        self.import_button = QPushButton("Импорт")
        self.import_button.clicked.connect(self._import_connections)
        header.addWidget(self.import_button)
        self.sync_button = QPushButton("Синхронизация")
        self.sync_button.clicked.connect(self._sync_imports)
        header.addWidget(self.sync_button)
        self.workspace_button = QPushButton("Пространства")
        self.workspace_button.clicked.connect(self._show_workspaces)
        header.addWidget(self.workspace_button)
        self.keys_button = QPushButton("SSH-ключи")
        self.keys_button.clicked.connect(self._show_key_manager)
        header.addWidget(self.keys_button)
        self.data_button = QPushButton("Данные")
        self.data_button.setToolTip(f"WinSSH UI {__version__}: резервные копии и обновления")
        self.data_button.clicked.connect(self._show_data_menu)
        header.addWidget(self.data_button)
        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("iconButton")
        self.refresh_button.setFixedWidth(42)
        self.refresh_button.setToolTip("Обновить подключения")
        self.refresh_button.clicked.connect(self.reload_connections)
        header.addWidget(self.refresh_button)
        root.addLayout(header)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchInput")
        self.search_edit.setPlaceholderText("Поиск по имени, адресу, пользователю или папке…")
        self.search_edit.setMinimumHeight(42)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _text: self._rebuild_connection_list())
        root.addWidget(self.search_edit)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_details_panel())
        splitter.setSizes([390, 690])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("secondary")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tool_status_label = QLabel(self.tools.message)
        self.tool_status_label.setObjectName("statusBadge")
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.tool_status_label)
        root.addLayout(footer)

        self.setCentralWidget(central)

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        connection_heading = QLabel("Подключения")
        connection_heading.setObjectName("sectionTitle")
        self.connection_count_label = QLabel("0")
        self.connection_count_label.setObjectName("countBadge")
        heading_row.addWidget(connection_heading)
        heading_row.addStretch()
        heading_row.addWidget(self.connection_count_label)
        layout.addLayout(heading_row)

        self.connection_list = QTreeWidget()
        self.connection_list.setHeaderHidden(True)
        self.connection_list.setRootIsDecorated(True)
        self.connection_list.setIndentation(18)
        self.connection_list.setIconSize(QSize(22, 22))
        self.connection_list.setAnimated(True)
        self.connection_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.connection_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.connection_list.customContextMenuRequested.connect(self._show_connection_context_menu)
        self.connection_list.itemDoubleClicked.connect(
            lambda _item, _column: self._launch(TerminalLaunchMode.NEW_TAB)
        )
        self.connection_list.itemExpanded.connect(
            lambda item: self._save_folder_expansion(item, True)
        )
        self.connection_list.itemCollapsed.connect(
            lambda item: self._save_folder_expansion(item, False)
        )
        self.connection_list.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.connection_list, 1)

        history_heading = QLabel("Недавние")
        history_heading.setObjectName("sectionTitle")
        layout.addWidget(history_heading)

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(135)
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.history_list)
        return panel

    def _build_details_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("detailsHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 13, 12, 13)
        self.device_icon_label = QLabel()
        self.device_icon_label.setObjectName("deviceIconTile")
        self.device_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.device_icon_label.setFixedSize(46, 46)
        hero_layout.addWidget(self.device_icon_label)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(2)
        self.alias_label = QLabel("Выберите подключение")
        self.alias_label.setObjectName("detailsTitle")
        self.endpoint_label = QLabel("Слева появятся хосты из ~/.ssh/config")
        self.endpoint_label.setObjectName("endpoint")
        self.endpoint_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hero_text.addWidget(self.alias_label)
        hero_text.addWidget(self.endpoint_label)
        hero_layout.addLayout(hero_text, 1)
        self.favorite_button = QPushButton("☆")
        self.favorite_button.setObjectName("favoriteButton")
        self.favorite_button.setCheckable(True)
        self.favorite_button.setFixedSize(42, 42)
        self.favorite_button.setToolTip("Добавить в избранное")
        self.favorite_button.clicked.connect(self._toggle_favorite)
        hero_layout.addWidget(self.favorite_button)
        layout.addWidget(hero)

        info_panel = QFrame()
        info_panel.setObjectName("infoPanel")
        info_grid = QGridLayout(info_panel)
        info_grid.setContentsMargins(14, 11, 14, 11)
        info_grid.setHorizontalSpacing(18)
        info_grid.setVerticalSpacing(8)
        self.identity_label = self._selectable_label("Определяется OpenSSH")
        self.proxy_label = self._selectable_label("Нет")
        self.config_label = self._selectable_label(str(self.config_path))
        self.origin_label = self._selectable_label("Создано вручную")
        for row, (name, value) in enumerate(
            (
                ("Ключ", self.identity_label),
                ("Переход через", self.proxy_label),
                ("Источник", self.origin_label),
                ("Файл настроек", self.config_label),
            )
        ):
            label = QLabel(name)
            label.setObjectName("fieldName")
            info_grid.addWidget(label, row, 0)
            info_grid.addWidget(value, row, 1)
        info_grid.setColumnStretch(1, 1)
        layout.addWidget(info_panel)

        security_title = QLabel("Безопасность и диагностика")
        security_title.setObjectName("sectionTitle")
        layout.addWidget(security_title)

        security_actions = QHBoxLayout()
        self.diagnostics_button = QPushButton("Проверить подключение")
        self.diagnostics_button.clicked.connect(self._show_diagnostics)
        self.host_key_button = QPushButton("Ключ хоста")
        self.host_key_button.clicked.connect(self._manage_host_key)
        if not self.host_key_manager.available:
            self.host_key_button.setToolTip("ssh-keygen.exe не найден в PATH")
        security_actions.addWidget(self.diagnostics_button)
        security_actions.addWidget(self.host_key_button)
        security_actions.addStretch()
        layout.addLayout(security_actions)

        organization = QLabel("Организация")
        organization.setObjectName("sectionTitle")
        layout.addWidget(organization)

        organization_grid = QGridLayout()
        organization_grid.setHorizontalSpacing(9)
        organization_grid.setVerticalSpacing(9)
        group_label = QLabel("Папка")
        group_label.setObjectName("fieldName")
        self.group_edit = QLineEdit()
        self.group_edit.setPlaceholderText("Папка, например Production/Web")
        icon_label = QLabel("Иконка")
        icon_label.setObjectName("fieldName")
        self.icon_combo = QComboBox()
        self.icon_combo.setIconSize(QSize(20, 20))
        self.icon_combo.addItem("Автоматически", None)
        for icon_name, label in DEVICE_ICON_OPTIONS:
            self.icon_combo.addItem(device_icon(icon_name), label, icon_name)
        self.icon_combo.currentIndexChanged.connect(self._preview_device_icon)
        self.group_edit.textChanged.connect(self._preview_device_icon)
        self.save_group_button = QPushButton("Сохранить")
        self.save_group_button.clicked.connect(self._save_group)
        organization_grid.addWidget(group_label, 0, 0)
        organization_grid.addWidget(self.group_edit, 0, 1)
        organization_grid.addWidget(icon_label, 1, 0)
        organization_grid.addWidget(self.icon_combo, 1, 1)
        organization_grid.addWidget(self.save_group_button, 0, 2, 2, 1)
        organization_grid.setColumnStretch(1, 1)
        layout.addLayout(organization_grid)

        management_title = QLabel("Управление подключением")
        management_title.setObjectName("sectionTitle")
        layout.addWidget(management_title)
        connection_actions = QHBoxLayout()
        self.edit_button = QPushButton("Настройки")
        self.edit_button.clicked.connect(self._edit_connection)
        self.clone_button = QPushButton("Создать копию")
        self.clone_button.clicked.connect(self._clone_connection)
        self.delete_button = QPushButton("Удалить")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete_connection)
        self.snippets_button = QPushButton("Команды")
        self.snippets_button.clicked.connect(self._show_snippets)
        connection_actions.addWidget(self.edit_button)
        connection_actions.addWidget(self.clone_button)
        connection_actions.addWidget(self.snippets_button)
        connection_actions.addWidget(self.delete_button)
        connection_actions.addStretch()
        layout.addLayout(connection_actions)
        layout.addStretch(1)

        launch_panel = QFrame()
        launch_panel.setObjectName("launchPanel")
        launch_layout = QVBoxLayout(launch_panel)
        launch_layout.setContentsMargins(14, 12, 14, 12)
        launch_layout.setSpacing(9)
        launch_header = QHBoxLayout()
        launch_title = QLabel("Подключение")
        launch_title.setObjectName("sectionTitle")
        launch_hint = QLabel("Windows Terminal · OpenSSH")
        launch_hint.setObjectName("secondary")
        launch_header.addWidget(launch_title)
        launch_header.addStretch()
        launch_header.addWidget(launch_hint)
        launch_layout.addLayout(launch_header)

        self.connect_button = QPushButton("Открыть терминал")
        self.connect_button.setObjectName("accentButton")
        self.connect_button.clicked.connect(lambda: self._launch(TerminalLaunchMode.NEW_TAB))
        self.split_button = QPushButton("Открыть справа")
        self.split_button.clicked.connect(lambda: self._launch(TerminalLaunchMode.SPLIT_RIGHT))
        self.tunnel_button = QPushButton("Запустить туннели")
        self.tunnel_button.clicked.connect(self._toggle_tunnels)
        self.winscp_button = QPushButton("WinSCP")
        self.winscp_button.clicked.connect(self._open_in_winscp)
        if not self.winscp_launcher.available:
            self.winscp_button.setToolTip("WinSCP.exe не найден")
        primary_actions = QHBoxLayout()
        primary_actions.setSpacing(10)
        primary_actions.addWidget(self.connect_button, 1)
        primary_actions.addWidget(self.split_button, 1)
        launch_layout.addLayout(primary_actions)
        launch_layout.addSpacing(3)
        secondary_actions = QHBoxLayout()
        secondary_actions.setSpacing(10)
        secondary_actions.addWidget(self.tunnel_button, 1)
        secondary_actions.addWidget(self.winscp_button, 1)
        launch_layout.addLayout(secondary_actions)
        layout.addWidget(launch_panel)

        self._set_details_enabled(False)

        scroll = QScrollArea()
        scroll.setObjectName("detailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        return scroll

    @staticmethod
    def _selectable_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _apply_style(self) -> None:
        QApplication.setFont(QFont("Segoe UI", 10))
        style_sheet = """
            QMainWindow, QDialog { background: #17191d; }
            QWidget { color: #e8eaed; }
            QWidget#appRoot { background: #17191d; }
            QLabel { background: transparent; border: none; }
            QLabel#title { color: #f7f8fa; font-size: 24px; font-weight: 650; }
            QLabel#detailsTitle { color: #ffffff; font-size: 21px; font-weight: 650; }
            QLabel#endpoint { color: #9ebce8; font-size: 12px; }
            QLabel#sectionTitle { color: #dfe3e8; font-size: 12px; font-weight: 650; }
            QLabel#fieldName { color: #8e96a3; font-size: 11px; }
            QLabel#secondary { color: #8f98a6; font-size: 11px; }
            QLabel#countBadge, QLabel#statusBadge {
                color: #aeb7c4;
                background: #2a2e35;
                border: 1px solid #373c45;
                border-radius: 9px;
                padding: 2px 8px;
                font-size: 10px;
            }
            QFrame#card {
                background: #22252a;
                border: 1px solid #30343b;
                border-radius: 12px;
            }
            QScrollArea#detailsScroll {
                background: transparent;
                border: none;
            }
            QFrame#detailsHero {
                background: #292d34;
                border: 1px solid #393e48;
                border-radius: 10px;
            }
            QLabel#deviceIconTile {
                background: #20242a;
                border: 1px solid #3b424d;
                border-radius: 9px;
            }
            QFrame#infoPanel {
                background: #1d2025;
                border: 1px solid #2d3138;
                border-radius: 9px;
            }
            QFrame#launchPanel {
                background: #1d2025;
                border: 1px solid #343942;
                border-radius: 10px;
            }
            QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
                color: #eef1f5;
                background: #292d33;
                border: 1px solid #3b414a;
                border-radius: 8px;
                padding: 8px 10px;
                selection-background-color: #2f6fd1;
            }
            QComboBox { padding-right: 40px; }
            QComboBox::drop-down {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 34px;
                margin: 1px;
                background: #25292f;
                border: none;
                border-left: 1px solid #3b414a;
                border-top-right-radius: 7px;
                border-bottom-right-radius: 7px;
            }
            QComboBox::drop-down:hover { background: #343941; }
            QComboBox::down-arrow {
                image: url(__COMBO_ARROW__);
                width: 11px;
                height: 7px;
            }
            QComboBox QAbstractItemView {
                color: #eef1f5;
                background: #25292f;
                border: 1px solid #414750;
                selection-color: #ffffff;
                selection-background-color: #2f6fd1;
                outline: none;
                padding: 4px;
            }
            QSpinBox { padding-right: 38px; }
            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border;
                width: 32px;
                background: #25292f;
                border: none;
                border-left: 1px solid #3b414a;
            }
            QSpinBox::up-button {
                subcontrol-position: top right;
                border-bottom: 1px solid #343941;
                border-top-right-radius: 7px;
            }
            QSpinBox::down-button {
                subcontrol-position: bottom right;
                border-bottom-right-radius: 7px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #343941; }
            QSpinBox::up-arrow {
                image: url(__SPIN_UP_ARROW__);
                width: 9px;
                height: 6px;
            }
            QSpinBox::down-arrow {
                image: url(__COMBO_ARROW__);
                width: 9px;
                height: 6px;
            }
            QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QComboBox:hover {
                border-color: #4a5260;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #4d8ff0;
                background: #2b3038;
            }
            QLineEdit#searchInput {
                background: #22252a;
                border-color: #343941;
                padding-left: 14px;
                font-size: 11px;
            }
            QPushButton {
                color: #e8ebef;
                background: #30343b;
                border: 1px solid #414750;
                border-radius: 8px;
                padding: 8px 13px;
                min-height: 18px;
            }
            QPushButton:hover { background: #383d46; border-color: #535b67; }
            QPushButton:pressed { background: #292d34; }
            QPushButton:disabled {
                color: #676e79;
                background: #26292e;
                border-color: #30343a;
            }
            QPushButton#accentButton {
                background: #246fe5;
                border-color: #3b82f6;
                color: white;
                font-weight: 600;
            }
            QPushButton#accentButton:hover { background: #2f7cf0; border-color: #63a0f7; }
            QPushButton#dangerButton { color: #ffb4b4; background: transparent; border-color: #56383d; }
            QPushButton#dangerButton:hover { color: #ffffff; background: #7f3038; border-color: #a7434d; }
            QPushButton#iconButton { padding: 7px 8px; font-size: 16px; }
            QPushButton#favoriteButton {
                color: #aab2bd;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 21px;
                padding: 0;
                font-size: 21px;
            }
            QPushButton#favoriteButton:hover { color: #ffd166; background: #343942; }
            QPushButton#favoriteButton:checked { color: #ffd166; background: #3a3527; }
            QListWidget, QTreeWidget {
                background: transparent;
                border: none;
                outline: none;
                show-decoration-selected: 0;
            }
            QListWidget::item, QTreeWidget::item {
                border-radius: 7px;
                padding: 7px 6px;
                margin: 1px 0;
            }
            QListWidget::item:selected, QTreeWidget::item:selected { background: #29476f; color: #ffffff; }
            QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected { background: #2b2f36; }
            QSplitter#mainSplitter::handle { background: #17191d; }
            QTabWidget::pane {
                background: #22252a;
                border: 1px solid #383d45;
                border-radius: 8px;
                top: -1px;
            }
            QTabBar::tab {
                color: #aeb6c2;
                background: #202328;
                border: 1px solid #343941;
                padding: 9px 16px;
                margin-right: 3px;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
            }
            QTabBar::tab:selected { color: #ffffff; background: #2b3037; border-bottom-color: #2b3037; }
            QTableWidget {
                background: #202328;
                alternate-background-color: #24282e;
                border: 1px solid #353a42;
                border-radius: 8px;
                gridline-color: #30353c;
                outline: none;
            }
            QHeaderView::section {
                color: #b9c1cc;
                background: #292d33;
                border: none;
                border-right: 1px solid #383d45;
                border-bottom: 1px solid #383d45;
                padding: 8px;
            }
            QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
            QScrollBar::handle:vertical { background: #454b55; border-radius: 4px; min-height: 28px; }
            QScrollBar::handle:vertical:hover { background: #59616e; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QToolTip {
                color: #f2f4f7;
                background: #30343b;
                border: 1px solid #505762;
                padding: 5px;
            }
            QMenu {
                color: #eef1f5;
                background: #25292f;
                border: 1px solid #414750;
                padding: 5px;
            }
            QMenu::item { padding: 7px 28px 7px 10px; border-radius: 5px; }
            QMenu::item:selected { background: #2f6fd1; color: white; }
            QMenu::item:disabled { color: #686f79; }
            QMenu::separator { height: 1px; background: #3b414a; margin: 5px 8px; }
            """
        style_sheet = style_sheet.replace(
            "__COMBO_ARROW__",
            resource_path("assets/ui/chevron-down.svg").as_posix(),
        ).replace(
            "__SPIN_UP_ARROW__",
            resource_path("assets/ui/chevron-up.svg").as_posix(),
        )
        self.setStyleSheet(style_sheet)

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
                    metadata.get(host.alias.casefold(), None).origin_type
                    if host.alias.casefold() in metadata
                    else None,
                    metadata.get(host.alias.casefold(), None).origin_identifier
                    if host.alias.casefold() in metadata
                    else None,
                    metadata.get(host.alias.casefold(), None).source_fingerprint
                    if host.alias.casefold() in metadata
                    else None,
                    metadata.get(host.alias.casefold(), None).imported_at_utc
                    if host.alias.casefold() in metadata
                    else None,
                    metadata.get(host.alias.casefold(), None).last_synced_at_utc
                    if host.alias.casefold() in metadata
                    else None,
                    metadata.get(host.alias.casefold(), None).icon_name
                    if host.alias.casefold() in metadata
                    else None,
                )
                for host in self.config_reader.read(self.config_path)
            ]
            self._rebuild_connection_list(selected_alias)
            self._reload_history()
            self.connection_count_label.setText(str(len(self.connections)))
            self.status_label.setText(f"Загружено подключений: {len(self.connections)}")
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось прочитать файлы настроек SSH", exception)

    def _config_files(self) -> tuple[Path, ...]:
        discovered = list(self.config_reader.discover_config_files(self.config_path))
        if self.config_path.resolve() not in discovered:
            discovered.insert(0, self.config_path.resolve())
        return tuple(discovered)

    def _create_connection(self) -> None:
        dialog = NewConnectionDialog(
            self,
            config_paths=self._config_files(),
            initial_config_path=self.config_path,
            config_editable=False,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft = dialog.draft()
        target_path = dialog.target_config_path() or self.config_path
        try:
            if draft.alias.casefold() in {item.alias.casefold() for item in self.connections}:
                raise ValueError(f"Host {draft.alias} уже существует в SSH-конфигурации")
            result = self.config_writer.append(target_path, draft)
            if not result.added:
                QMessageBox.information(
                    self,
                    "Алиас уже существует",
                    f"Host {draft.alias} уже есть в настройках SSH. Выберите другой алиас.",
                )
                return
            self.catalog.save_metadata(
                ConnectionMetadata(draft.alias, draft.is_favorite, draft.group_name)
            )
            self.reload_connections()
            self._rebuild_connection_list(draft.alias)
            self.status_label.setText(f"Подключение {draft.alias} сохранено в {target_path}")
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
            candidates_by_alias = {candidate.alias.casefold(): candidate for candidate in candidates}
            now = datetime.now(UTC).isoformat()
            for draft in result.added:
                candidate = candidates_by_alias[draft.alias.casefold()]
                self.catalog.save_metadata(
                    self._import_metadata(candidate, draft.alias, draft.group_name, False, now, now)
                )
            self.reload_connections()
            message = f"Импортировано подключений: {len(result.added)}"
            if result.skipped_aliases:
                message += f"; пропущены существующие алиасы: {', '.join(result.skipped_aliases)}"
            self.status_label.setText(message)
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось импортировать подключения", exception)

    def _sync_imports(self) -> None:
        try:
            scan = self.client_importer.scan_known_sources()
            metadata = self.catalog.get_all_metadata()
        except (OSError, ValueError, sqlite3.Error) as exception:
            self._show_error("Не удалось просканировать источники импорта", exception)
            return

        existing = {connection.alias.casefold(): connection for connection in self.connections}
        by_origin = {
            (item.origin_type.casefold(), item.origin_identifier.casefold()): item
            for item in metadata.values()
            if item.origin_type and item.origin_identifier
        }
        additions: list[ImportCandidate] = []
        adoptions: list[tuple[ImportCandidate, ConnectionItem]] = []
        updates: list[tuple[ImportCandidate, ConnectionItem, ConnectionMetadata]] = []
        unchanged: list[tuple[ImportCandidate, ConnectionMetadata]] = []
        conflicts: list[str] = []
        seen_origins: set[tuple[str, str]] = set()

        for candidate in scan.candidates:
            origin_key = (candidate.source.casefold(), candidate.origin_identifier.casefold())
            if origin_key in seen_origins:
                continue
            seen_origins.add(origin_key)
            origin_metadata = by_origin.get(origin_key)
            if origin_metadata is not None:
                current = existing.get(origin_metadata.alias.casefold())
                if current is None:
                    conflicts.append(f"{candidate.source}: {candidate.name} — локальный Host удалён")
                    continue
                current_fingerprint = self._host_fingerprint(current)
                if candidate.source_fingerprint == origin_metadata.source_fingerprint:
                    unchanged.append((candidate, origin_metadata))
                elif current_fingerprint == origin_metadata.source_fingerprint:
                    updates.append((candidate, current, origin_metadata))
                else:
                    conflicts.append(
                        f"{candidate.source}: {candidate.name} — изменены и источник, и локальный Host"
                    )
                continue

            current = existing.get(candidate.alias.casefold())
            if current is None:
                additions.append(candidate)
            elif current.origin_type:
                conflicts.append(
                    f"{candidate.source}: {candidate.name} — алиас занят другим источником"
                )
            elif self._host_fingerprint(current) == candidate.source_fingerprint:
                adoptions.append((candidate, current))
            else:
                conflicts.append(
                    f"{candidate.source}: {candidate.name} — алиас совпадает, параметры отличаются"
                )

        summary = (
            f"Новые: {len(additions)}\n"
            f"Привязать существующие: {len(adoptions)}\n"
            f"Обновить: {len(updates)}\n"
            f"Без изменений: {len(unchanged)}\n"
            f"Конфликты (будут пропущены): {len(conflicts)}"
        )
        if conflicts:
            summary += "\n\n" + "\n".join(conflicts[:10])
            if len(conflicts) > 10:
                summary += f"\n…и ещё {len(conflicts) - 10}"
        if scan.warnings:
            summary += "\n\nПредупреждения сканирования:\n" + "\n".join(scan.warnings[:5])
        answer = QMessageBox.question(
            self,
            "Синхронизация импортов",
            summary + "\n\nПрименить безопасные изменения?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        snapshot: Path | None = None
        now = datetime.now(UTC).isoformat()
        try:
            if (additions or updates) and self.config_path.exists():
                snapshot = self.config_path.with_name("config.winsshui-sync.bak")
                shutil.copy2(self.config_path, snapshot)

            for candidate, current, origin_metadata in updates:
                source_draft = candidate.to_draft()
                draft = replace(
                    source_draft,
                    alias=current.alias,
                    proxy_jump=current.host.proxy_jump,
                    connect_timeout=current.host.connect_timeout,
                    server_alive_interval=current.host.server_alive_interval,
                    server_alive_count_max=current.host.server_alive_count_max,
                    forward_agent=current.host.forward_agent,
                    compression=current.host.compression,
                    request_tty=current.host.request_tty,
                    remote_command=current.host.remote_command,
                    local_forwards=current.host.local_forwards,
                    remote_forwards=current.host.remote_forwards,
                    dynamic_forwards=current.host.dynamic_forwards,
                    group_name=current.group_name,
                    is_favorite=current.is_favorite,
                )
                self.config_writer.update(
                    Path(current.host.source_path or self.config_path),
                    current.alias,
                    draft,
                )
                self.catalog.save_metadata(
                    self._import_metadata(
                        candidate,
                        current.alias,
                        current.group_name,
                        current.is_favorite,
                        origin_metadata.imported_at_utc or now,
                        now,
                        current.icon_name,
                    )
                )

            added_result = self.config_writer.append_many(
                self.config_path, [candidate.to_draft() for candidate in additions]
            )
            additions_by_alias = {candidate.alias.casefold(): candidate for candidate in additions}
            for draft in added_result.added:
                candidate = additions_by_alias[draft.alias.casefold()]
                self.catalog.save_metadata(
                    self._import_metadata(
                        candidate, draft.alias, draft.group_name, False, now, now
                    )
                )

            for candidate, current in adoptions:
                self.catalog.save_metadata(
                    self._import_metadata(
                        candidate,
                        current.alias,
                        current.group_name,
                        current.is_favorite,
                        now,
                        now,
                        current.icon_name,
                    )
                )
            for candidate, item in unchanged:
                self.catalog.save_metadata(
                    self._import_metadata(
                        candidate,
                        item.alias,
                        item.group_name,
                        item.is_favorite,
                        item.imported_at_utc or now,
                        now,
                        item.icon_name,
                    )
                )
            self.reload_connections()
            self.status_label.setText(
                f"Синхронизация завершена: добавлено {len(added_result.added)}, "
                f"обновлено {len(updates)}, привязано {len(adoptions)}, конфликтов {len(conflicts)}"
                + (f"; снимок: {snapshot}" if snapshot else "")
            )
        except (OSError, ValueError, LookupError, sqlite3.Error) as exception:
            self._show_error(
                "Синхронизация прервана"
                + (f"; исходный снимок сохранён в {snapshot}" if snapshot else ""),
                exception,
            )

    def _edit_connection(self) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        dialog = NewConnectionDialog(
            self,
            self._draft_from_connection(connection),
            f"Редактирование — {connection.alias}",
            config_paths=(Path(connection.host.source_path or self.config_path),),
            initial_config_path=Path(connection.host.source_path or self.config_path),
            config_editable=False,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft = dialog.draft()
        try:
            source_path = Path(connection.host.source_path or self.config_path)
            result = self.config_writer.update(source_path, connection.alias, draft)
            self.catalog.replace_metadata(
                connection.alias,
                ConnectionMetadata(
                    draft.alias,
                    draft.is_favorite,
                    draft.group_name,
                    connection.origin_type,
                    connection.origin_identifier,
                    connection.source_fingerprint,
                    connection.imported_at_utc,
                    connection.last_synced_at_utc,
                    connection.icon_name,
                ),
            )
            self.reload_connections()
            self._rebuild_connection_list(draft.alias)
            self.status_label.setText(
                f"Подключение {draft.alias} обновлено; резервная копия: {result.backup_path}"
            )
        except (OSError, ValueError, LookupError, sqlite3.Error) as exception:
            self._show_error("Не удалось обновить подключение", exception)

    def _clone_connection(self) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        source = self._draft_from_connection(connection)
        clone = SshConnectionDraft(
            **{
                field: getattr(source, field)
                for field in source.__dataclass_fields__
                if field not in ("alias", "is_favorite")
            },
            alias=f"{source.alias}-copy",
            is_favorite=False,
        )
        dialog = NewConnectionDialog(
            self,
            clone,
            f"Клонирование — {connection.alias}",
            config_paths=self._config_files(),
            initial_config_path=Path(connection.host.source_path or self.config_path),
            config_editable=False,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        draft = dialog.draft()
        target_path = dialog.target_config_path() or self.config_path
        try:
            if draft.alias.casefold() in {item.alias.casefold() for item in self.connections}:
                raise ValueError(f"Host {draft.alias} уже существует в SSH-конфигурации")
            result = self.config_writer.append(target_path, draft)
            if not result.added:
                raise ValueError(f"Host {draft.alias} уже существует")
            self.catalog.save_metadata(
                ConnectionMetadata(
                    draft.alias,
                    draft.is_favorite,
                    draft.group_name,
                    icon_name=connection.icon_name,
                )
            )
            self.reload_connections()
            self._rebuild_connection_list(draft.alias)
            self.status_label.setText(f"Создана копия подключения {draft.alias}")
        except (OSError, ValueError, sqlite3.Error) as exception:
            self._show_error("Не удалось клонировать подключение", exception)

    def _delete_connection(self) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        source_path = Path(connection.host.source_path or self.config_path)
        answer = QMessageBox.warning(
            self,
            "Удаление SSH-подключения",
            f"Удалить Host {connection.alias} из {source_path}?\n\n"
            "Перед изменением будет создан config.bak.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.config_writer.delete(source_path, connection.alias)
            self.catalog.delete_metadata(connection.alias)
            self.reload_connections()
            self.status_label.setText(
                f"Подключение {connection.alias} удалено; резервная копия: {result.backup_path}"
            )
        except (OSError, LookupError, sqlite3.Error) as exception:
            self._show_error("Не удалось удалить подключение", exception)

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
        try:
            folder_states = self.catalog.get_folder_states()
        except sqlite3.Error:
            folder_states = {}
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
                    folder_item = QTreeWidgetItem([part])
                    folder_item.setIcon(0, folder_icon())
                    state_key = f"folder:{key}"
                    folder_item.setData(0, int(Qt.ItemDataRole.UserRole) + 1, state_key)
                    folder_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    folder_font = folder_item.font(0)
                    folder_font.setBold(True)
                    folder_item.setFont(0, folder_font)
                    parent.addChild(folder_item)
                    folder_item.setExpanded(folder_states.get(state_key, True))
                    folder_items[key] = folder_item
                parent = folder_item
            return parent

        def connection_item(connection: ConnectionItem) -> QTreeWidgetItem:
            star = "★" if connection.is_favorite else "☆"
            item = QTreeWidgetItem(
                [f"{star}  {connection.alias}\n     {connection.host.display_endpoint}"]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, connection)
            icon_name = resolve_device_icon(
                connection.icon_name,
                connection.alias,
                connection.host.hostname,
                connection.group_name,
            )
            item.setIcon(0, device_icon(icon_name))
            item.setToolTip(0, connection.host.display_endpoint)
            return item

        favorites = [connection for connection in filtered if connection.is_favorite]
        if favorites:
            favorite_folder = QTreeWidgetItem(["★  Избранное"])
            favorite_folder.setIcon(0, folder_icon())
            favorite_state_key = "virtual:favorites"
            favorite_folder.setData(
                0,
                int(Qt.ItemDataRole.UserRole) + 1,
                favorite_state_key,
            )
            favorite_folder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            favorite_font = favorite_folder.font(0)
            favorite_font.setBold(True)
            favorite_folder.setFont(0, favorite_font)
            root.addChild(favorite_folder)
            favorite_folder.setExpanded(folder_states.get(favorite_state_key, True))
            for connection in favorites:
                item = connection_item(connection)
                favorite_folder.addChild(item)
                first_connection_item = first_connection_item or item
                if (
                    selected_item is None
                    and connection.alias.casefold() == (alias_to_restore or "").casefold()
                ):
                    selected_item = item

        for connection in filtered:
            item = connection_item(connection)
            folder_parent(connection.group_name).addChild(item)
            first_connection_item = first_connection_item or item
            if (
                selected_item is None
                and connection.alias.casefold() == (alias_to_restore or "").casefold()
            ):
                selected_item = item
        self.connection_list.blockSignals(False)
        if selected_item is not None:
            self.connection_list.setCurrentItem(selected_item)
        elif first_connection_item is not None and alias_to_restore is None:
            self.connection_list.setCurrentItem(first_connection_item)
        else:
            self._selection_changed(None, None)

    def _save_folder_expansion(self, item: QTreeWidgetItem, is_expanded: bool) -> None:
        folder_key = item.data(0, int(Qt.ItemDataRole.UserRole) + 1)
        if not isinstance(folder_key, str):
            return
        try:
            self.catalog.save_folder_state(folder_key, is_expanded)
        except sqlite3.Error as exception:
            self.status_label.setText(f"Не удалось сохранить состояние папки: {exception}")

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
        self._effective_configuration = None
        if not isinstance(connection, ConnectionItem):
            self._set_details_enabled(False)
            self.alias_label.setText("Выберите подключение")
            self.endpoint_label.setText("Слева появятся хосты из ~/.ssh/config")
            self.identity_label.setText("Определяется OpenSSH")
            self.proxy_label.setText("Нет")
            self.origin_label.setText("Создано вручную")
            self.config_label.setText(str(self.config_path))
            self.group_edit.clear()
            self.icon_combo.setCurrentIndex(0)
            self.device_icon_label.clear()
            self.favorite_button.setChecked(False)
            self.favorite_button.setText("☆")
            self.favorite_button.setToolTip("Добавить в избранное")
            self._update_tunnel_button(None)
            return

        self._set_details_enabled(True)
        self.alias_label.setText(connection.alias)
        self.endpoint_label.setText("Получаю эффективную конфигурацию…")
        self.identity_label.setText(connection.host.identity_file or "Определяется OpenSSH")
        self.proxy_label.setText(connection.host.proxy_jump or "Нет")
        self.origin_label.setText(
            f"{connection.origin_type}: {connection.origin_identifier}"
            + (f" · синхр. {connection.last_synced_at_utc}" if connection.last_synced_at_utc else "")
            if connection.origin_type
            else "Создано вручную"
        )
        self.config_label.setText(connection.host.source_path or str(self.config_path))
        self.group_edit.setText(connection.group_name or "")
        icon_index = self.icon_combo.findData(connection.icon_name)
        self.icon_combo.setCurrentIndex(max(0, icon_index))
        icon_name = resolve_device_icon(
            connection.icon_name,
            connection.alias,
            connection.host.hostname,
            connection.group_name,
        )
        self.device_icon_label.setPixmap(device_icon(icon_name).pixmap(30, 30))
        self.favorite_button.setChecked(connection.is_favorite)
        self.favorite_button.setText("★" if connection.is_favorite else "☆")
        self.favorite_button.setToolTip(
            "Удалить из избранного" if connection.is_favorite else "Добавить в избранное"
        )
        self._resolve_effective_configuration(connection)
        self._update_tunnel_button(connection)

    def _set_details_enabled(self, has_selection: bool) -> None:
        can_connect = has_selection and self.tools.can_connect
        self.connect_button.setEnabled(can_connect)
        self.split_button.setEnabled(can_connect)
        self.favorite_button.setEnabled(has_selection)
        self.group_edit.setEnabled(has_selection)
        self.icon_combo.setEnabled(has_selection)
        self.save_group_button.setEnabled(has_selection)
        self.host_key_button.setEnabled(has_selection and self.host_key_manager.available)
        self.diagnostics_button.setEnabled(has_selection and self.tools.ssh_path is not None)
        self.edit_button.setEnabled(has_selection)
        self.clone_button.setEnabled(has_selection)
        self.snippets_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.winscp_button.setEnabled(has_selection and self.winscp_launcher.available)
        if not has_selection:
            self.tunnel_button.setEnabled(False)

    def _preview_device_icon(self, _value: object = None) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        selected_icon = self.icon_combo.currentData()
        icon_name = resolve_device_icon(
            selected_icon if isinstance(selected_icon, str) else None,
            connection.alias,
            connection.host.hostname,
            self.group_edit.text().strip() or None,
        )
        self.device_icon_label.setPixmap(device_icon(icon_name).pixmap(30, 30))

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
        if self._update_reply is not None:
            self._update_reply.abort()
            self._update_reply = None
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
        for tunnel in tuple(self._tunnel_processes.values()):
            try:
                tunnel.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            if tunnel.state() != QProcess.ProcessState.NotRunning:
                tunnel.terminate()
                if not tunnel.waitForFinished(700):
                    tunnel.kill()
                    tunnel.waitForFinished(300)
        self._tunnel_processes.clear()
        super().closeEvent(event)

    def _show_effective_configuration(self, configuration: EffectiveSshConfiguration) -> None:
        if self._selected_connection() and self._selected_connection().alias == configuration.alias:
            self._effective_configuration = configuration
            self.endpoint_label.setText(configuration.endpoint)
            self.identity_label.setText(configuration.identity_file)
            self.proxy_label.setText(configuration.proxy_jump or "Нет")

    def _manage_host_key(self) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        effective = self._effective_configuration
        if effective and effective.alias == connection.alias:
            hostname, port = effective.hostname, effective.port
        else:
            hostname = connection.host.hostname or connection.alias
            port = connection.host.port or 22

        try:
            status = self.host_key_manager.inspect(hostname, port)
        except (OSError, RuntimeError, TimeoutError, ValueError) as exception:
            self._show_error("Не удалось проверить ключ хоста", exception)
            return

        dialog = QMessageBox(self)
        dialog.setWindowTitle(f"Ключ SSH-хоста — {connection.alias}")
        dialog.setIcon(
            QMessageBox.Icon.Warning if status.found else QMessageBox.Icon.Information
        )
        dialog.setText(f"Хост: {status.lookup_target}")
        dialog.setInformativeText(
            "Если OpenSSH сообщает REMOTE HOST IDENTIFICATION HAS CHANGED, сначала "
            "подтвердите новый fingerprint у администратора сервера. Удаление старой записи "
            "не означает доверие новому ключу."
            if status.found
            else "Для этого адреса нет сохранённого ключа. При первом подключении OpenSSH "
            "попросит проверить и принять fingerprint сервера."
        )
        dialog.setDetailedText(f"Файл: {status.known_hosts_path}\n\n{status.details}")
        close_button = dialog.addButton("Закрыть", QMessageBox.ButtonRole.RejectRole)
        remove_button = None
        if status.found:
            remove_button = dialog.addButton(
                "Удалить старый ключ…", QMessageBox.ButtonRole.DestructiveRole
            )
        dialog.setDefaultButton(close_button)
        dialog.exec()
        if remove_button is None or dialog.clickedButton() is not remove_button:
            return

        confirmation = QMessageBox(self)
        confirmation.setWindowTitle("Подтверждение смены ключа")
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setText(f"Удалить сохранённый ключ для {status.lookup_target}?")
        confirmation.setInformativeText(
            "Продолжайте только если сервер был переустановлен или смена ключа подтверждена "
            "администратором. Будет создана резервная копия known_hosts. Новый ключ приложение "
            "автоматически принимать не будет."
        )
        confirmation.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirmation.button(QMessageBox.StandardButton.Yes).setText("Удалить старый ключ")
        confirmation.button(QMessageBox.StandardButton.No).setText("Отмена")
        confirmation.setDefaultButton(QMessageBox.StandardButton.No)
        if confirmation.exec() != QMessageBox.StandardButton.Yes:
            return

        try:
            result = self.host_key_manager.remove(hostname, port)
        except (OSError, RuntimeError, TimeoutError, ValueError, LookupError) as exception:
            self._show_error("Не удалось удалить старый ключ", exception)
            return
        self.status_label.setText(
            f"Старый ключ {result.lookup_target} удалён; копия: {result.backup_path}"
        )
        QMessageBox.information(
            self,
            "Старый ключ удалён",
            f"Резервная копия:\n{result.backup_path}\n\n"
            "Подключитесь снова и сравните показанный SHA-256 fingerprint с доверенным "
            "значением администратора сервера.",
        )

    def _show_diagnostics(self) -> None:
        connection = self._selected_connection()
        if connection:
            DiagnosticsDialog(self.ssh_diagnostics, connection.alias, self).exec()

    def _show_key_manager(self) -> None:
        SshKeyManagerDialog(self.key_manager, self).exec()

    def _show_data_menu(self) -> None:
        menu = QMenu(self)
        update_action = menu.addAction(f"Проверить обновления…  (версия {__version__})")
        update_action.triggered.connect(lambda: self._check_updates(silent=False))
        menu.addSeparator()
        export_action = menu.addAction("Экспортировать резервную копию…")
        export_action.triggered.connect(self._export_backup)
        restore_action = menu.addAction("Восстановить из копии…")
        restore_action.triggered.connect(self._restore_backup)
        menu.exec(self.data_button.mapToGlobal(QPoint(0, self.data_button.height())))

    def _auto_check_updates(self) -> None:
        try:
            last_checked = self.catalog.get_setting("updates.last_checked_utc")
            if last_checked:
                checked_at = datetime.fromisoformat(last_checked)
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=UTC)
                if datetime.now(UTC) - checked_at < timedelta(days=1):
                    return
        except (OSError, sqlite3.Error, ValueError):
            pass
        self._check_updates(silent=True)

    def _check_updates(self, silent: bool = False) -> None:
        if self._update_reply is not None:
            if not silent:
                self.status_label.setText("Проверка обновлений уже выполняется…")
            return
        if silent:
            try:
                self.catalog.save_setting("updates.last_checked_utc", datetime.now(UTC).isoformat())
            except (OSError, sqlite3.Error):
                pass
        request = QNetworkRequest(QUrl(LATEST_RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2026-03-10")
        request.setRawHeader(b"User-Agent", f"WinSSH-UI/{__version__}".encode("ascii"))
        reply = self._update_manager.get(request)
        self._update_reply = reply
        reply.finished.connect(lambda: self._update_check_finished(reply, silent))
        if not silent:
            self.status_label.setText("Проверяю обновления…")

    def _update_check_finished(self, reply: QNetworkReply, silent: bool) -> None:
        if reply is not self._update_reply:
            reply.deleteLater()
            return
        self._update_reply = None
        error = reply.error()
        error_text = reply.errorString()
        payload = bytes(reply.readAll())
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "Проверка обновлений",
                    f"Не удалось получить данные о релизе.\n\n{error_text}",
                )
            return
        try:
            release = parse_latest_release(payload)
            self.catalog.save_setting("updates.last_checked_utc", datetime.now(UTC).isoformat())
        except (ValueError, OSError, sqlite3.Error) as exception:
            if not silent:
                QMessageBox.warning(self, "Проверка обновлений", str(exception))
            return
        if not is_newer_version(release.version, __version__):
            if not silent:
                QMessageBox.information(
                    self,
                    "Проверка обновлений",
                    f"Установлена актуальная версия WinSSH UI {__version__}.",
                )
            return

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Доступно обновление")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(f"Доступна WinSSH UI {release.version}")
        details = f"Установлена версия: {__version__}\nРелиз: {release.title}"
        if release.notes:
            notes = release.notes[:1200]
            details += f"\n\n{notes}{'…' if len(release.notes) > len(notes) else ''}"
        dialog.setInformativeText(details)
        open_text = "Скачать EXE" if release.download_url else "Открыть страницу релиза"
        open_button = dialog.addButton(open_text, QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(release.download_url or release.page_url))

    def _export_backup(self) -> None:
        default_name = f"winsshui-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        filename, _filter = QFileDialog.getSaveFileName(
            self,
            "Экспорт резервной копии",
            str(Path.home() / default_name),
            "Архив WinSSH UI (*.zip)",
        )
        if not filename:
            return
        try:
            destination = self.backup_manager.export(Path(filename))
        except (OSError, ValueError, sqlite3.Error) as exception:
            self._show_error("Не удалось создать резервную копию", exception)
            return
        self.status_label.setText(f"Резервная копия сохранена: {destination}")

    def _restore_backup(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Восстановление WinSSH UI",
            str(Path.home()),
            "Архив WinSSH UI (*.zip)",
        )
        if not filename:
            return
        answer = QMessageBox.warning(
            self,
            "Восстановить резервную копию?",
            "Текущие файлы настроек SSH и локальный каталог будут заменены. Перед заменой "
            "для каждого существующего файла будет создана копия *.before-restore-*.bak.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = self.backup_manager.restore(Path(filename))
            self.catalog.initialize()
            self.reload_connections()
        except (OSError, ValueError, sqlite3.Error) as exception:
            self._show_error("Не удалось восстановить резервную копию", exception)
            return
        self.status_label.setText(f"Восстановлено файлов: {len(restored)}")

    def _show_snippets(self) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        try:
            CommandSnippetsDialog(self.catalog, connection.alias, self).exec()
        except sqlite3.Error as exception:
            self._show_error("Не удалось открыть командные сниппеты", exception)

    def _run_snippet(self, snippet: CommandSnippet) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        try:
            self.terminal_launcher.launch_snippet(
                connection.host,
                snippet.command,
                f"{connection.alias} · {snippet.name}",
            )
            self.status_label.setText(
                f"Запускаю «{snippet.name}» на {connection.alias} в Windows Terminal…"
            )
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось запустить команду", exception)

    def _show_connection_context_menu(self, position: QPoint) -> None:
        item = self.connection_list.itemAt(position)
        connection = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(connection, ConnectionItem):
            return
        self.connection_list.setCurrentItem(item)
        menu = QMenu(self)
        open_action = menu.addAction("Открыть терминал")
        open_action.setEnabled(self.tools.can_connect)
        open_action.triggered.connect(lambda: self._launch(TerminalLaunchMode.NEW_TAB))
        split_action = menu.addAction("Открыть справа")
        split_action.setEnabled(self.tools.can_connect)
        split_action.triggered.connect(lambda: self._launch(TerminalLaunchMode.SPLIT_RIGHT))

        snippets_menu = menu.addMenu("Команды")
        try:
            snippets = self.catalog.get_command_snippets(connection.alias)
        except sqlite3.Error:
            snippets = []
        if snippets:
            for snippet in snippets:
                action = snippets_menu.addAction(snippet.name)
                action.setToolTip(snippet.command)
                action.triggered.connect(
                    lambda _checked=False, selected=snippet: self._run_snippet(selected)
                )
            snippets_menu.addSeparator()
        manage_snippets = snippets_menu.addAction("Настроить команды…")
        manage_snippets.triggered.connect(self._show_snippets)

        menu.addSeparator()
        winscp_action = menu.addAction("Открыть в WinSCP")
        winscp_action.setEnabled(self.winscp_launcher.available)
        winscp_action.triggered.connect(self._open_in_winscp)
        diagnostics_action = menu.addAction("Проверить подключение")
        diagnostics_action.setEnabled(self.tools.ssh_path is not None)
        diagnostics_action.triggered.connect(self._show_diagnostics)
        tunnels_action = menu.addAction("Запустить / остановить туннели")
        tunnels_action.setEnabled(self.tunnel_button.isEnabled())
        tunnels_action.triggered.connect(self._toggle_tunnels)

        copy_menu = menu.addMenu("Копировать")
        copy_ssh = copy_menu.addAction(f"ssh {connection.alias}")
        copy_ssh.triggered.connect(
            lambda: QApplication.clipboard().setText(f"ssh {connection.alias}")
        )
        copy_address = copy_menu.addAction("Адрес подключения")
        copy_address.triggered.connect(
            lambda: QApplication.clipboard().setText(connection.host.display_endpoint)
        )

        menu.addSeparator()
        favorite_action = QAction("Избранное", menu)
        favorite_action.setCheckable(True)
        favorite_action.setChecked(connection.is_favorite)
        favorite_action.triggered.connect(self._toggle_favorite)
        menu.addAction(favorite_action)
        edit_action = menu.addAction("Настройки…")
        edit_action.triggered.connect(self._edit_connection)
        clone_action = menu.addAction("Создать копию…")
        clone_action.triggered.connect(self._clone_connection)
        delete_action = menu.addAction("Удалить…")
        delete_action.triggered.connect(self._delete_connection)
        menu.exec(self.connection_list.viewport().mapToGlobal(position))

    def _show_workspaces(self) -> None:
        try:
            dialog = WorkspaceDialog(self.catalog, self.connections, self)
        except sqlite3.Error as exception:
            self._show_error("Не удалось открыть рабочие пространства", exception)
            return
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.launch_items:
            return
        by_alias = {connection.alias.casefold(): connection for connection in self.connections}
        items = [
            (by_alias[item.alias.casefold()].host, item.mode)
            for item in dialog.launch_items
            if item.alias.casefold() in by_alias
        ]
        if not items:
            QMessageBox.warning(
                self,
                "Рабочее пространство",
                "Подключения из пространства больше не найдены в настройках SSH.",
            )
            return
        try:
            self.terminal_launcher.launch_workspace(items)
            for host, mode in items:
                self.catalog.record_launch(host.alias, mode)
            self._reload_history()
            self.status_label.setText(f"Открываю рабочее пространство: подключений {len(items)}")
        except (OSError, ValueError, sqlite3.Error) as exception:
            self._show_error("Не удалось запустить рабочее пространство", exception)

    def _open_in_winscp(self) -> None:
        connection = self._selected_connection()
        if not connection:
            return
        effective = self._effective_configuration
        host = connection.host
        if effective and effective.alias == connection.alias:
            host = replace(
                host,
                hostname=effective.hostname,
                user=effective.user,
                port=effective.port,
            )
        if host.proxy_jump:
            answer = QMessageBox.warning(
                self,
                "Промежуточный хост и WinSCP",
                "Автоматическая передача цепочки промежуточных хостов в WinSCP пока не поддерживается. "
                "WinSCP попробует прямое подключение. Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.winscp_launcher.launch(host)
            self.status_label.setText(f"Открываю {connection.alias} в WinSCP…")
        except (OSError, ValueError) as exception:
            self._show_error("Не удалось запустить WinSCP", exception)

    def _toggle_tunnels(self) -> None:
        connection = self._selected_connection()
        if not connection or not self.tools.ssh_path:
            return
        key = connection.alias.casefold()
        process = self._tunnel_processes.get(key)
        if process and process.state() != QProcess.ProcessState.NotRunning:
            self._stopping_tunnels.add(key)
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
            self.status_label.setText(f"Туннели {connection.alias} остановлены")
            return
        if not self._has_tunnels(connection):
            QMessageBox.information(
                self,
                "Туннели не настроены",
                "Добавьте LocalForward, RemoteForward или DynamicForward через «Редактировать».",
            )
            return

        process = QProcess(self)
        process.setProgram(self.tools.ssh_path)
        process.setArguments(ManagedTunnelCommand.create(connection.alias))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._tunnel_processes[key] = process
        process.started.connect(lambda: self._tunnel_started(connection.alias, process))
        process.finished.connect(
            lambda exit_code, _status: self._tunnel_finished(
                connection.alias, process, exit_code
            )
        )
        process.start()
        self.status_label.setText(f"Запускаю туннели {connection.alias}…")

    def _tunnel_started(self, alias: str, process: QProcess) -> None:
        if self._tunnel_processes.get(alias.casefold()) is process:
            self.status_label.setText(f"Туннели {alias} запущены")
            self._update_tunnel_button(self._selected_connection())

    def _tunnel_finished(self, alias: str, process: QProcess, exit_code: int) -> None:
        key = alias.casefold()
        intentionally_stopped = key in self._stopping_tunnels
        self._stopping_tunnels.discard(key)
        if self._tunnel_processes.get(key) is process:
            self._tunnel_processes.pop(key, None)
        output = bytes(process.readAll()).decode("utf-8", errors="replace").strip()
        process.deleteLater()
        selected = self._selected_connection()
        self._update_tunnel_button(selected)
        if intentionally_stopped or exit_code == 0:
            self.status_label.setText(f"Туннели {alias} остановлены")
        else:
            message = output or f"ssh завершился с кодом {exit_code}"
            self.status_label.setText(f"Не удалось запустить туннели {alias}: {message}")
            QMessageBox.warning(
                self,
                f"Туннели {alias}",
                f"{message}\n\nДля фонового туннеля используйте ключ или ssh-agent. "
                "Проверить причину можно кнопкой «Проверить подключение»."
            )

    def _update_tunnel_button(self, connection: ConnectionItem | None) -> None:
        if not connection:
            self.tunnel_button.setText("Запустить туннели")
            self.tunnel_button.setEnabled(False)
            return
        process = self._tunnel_processes.get(connection.alias.casefold())
        active = process is not None and process.state() != QProcess.ProcessState.NotRunning
        self.tunnel_button.setText("Остановить туннели" if active else "Запустить туннели")
        self.tunnel_button.setEnabled(
            self.tools.ssh_path is not None and (active or self._has_tunnels(connection))
        )

    @staticmethod
    def _has_tunnels(connection: ConnectionItem) -> bool:
        host = connection.host
        return bool(host.local_forwards or host.remote_forwards or host.dynamic_forwards)

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
        previous_icon = connection.icon_name
        connection.group_name = self.group_edit.text().strip() or None
        selected_icon = self.icon_combo.currentData()
        connection.icon_name = selected_icon if isinstance(selected_icon, str) else None
        try:
            self.catalog.save_metadata(connection.metadata())
            self.status_label.setText(f"Организация для {connection.alias} сохранена")
            self._rebuild_connection_list(connection.alias)
        except Exception as exception:
            connection.group_name = previous_group
            connection.icon_name = previous_icon
            self._show_error("Не удалось сохранить организацию", exception)

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

    @staticmethod
    def _draft_from_connection(connection: ConnectionItem) -> SshConnectionDraft:
        host = connection.host
        return SshConnectionDraft(
            alias=host.alias,
            hostname=host.hostname or host.alias,
            user=host.user,
            port=host.port or 22,
            identity_file=host.identity_file,
            proxy_jump=host.proxy_jump,
            connect_timeout=host.connect_timeout,
            server_alive_interval=host.server_alive_interval,
            server_alive_count_max=host.server_alive_count_max,
            forward_agent=host.forward_agent,
            compression=host.compression,
            request_tty=host.request_tty,
            remote_command=host.remote_command,
            local_forwards=host.local_forwards,
            remote_forwards=host.remote_forwards,
            dynamic_forwards=host.dynamic_forwards,
            group_name=connection.group_name,
            is_favorite=connection.is_favorite,
        )

    @staticmethod
    def _host_fingerprint(connection: ConnectionItem) -> str:
        host = connection.host
        return connection_fingerprint(
            host.hostname or host.alias,
            host.user,
            host.port or 22,
            host.identity_file,
        )

    @staticmethod
    def _import_metadata(
        candidate: ImportCandidate,
        alias: str,
        group_name: str | None,
        is_favorite: bool,
        imported_at_utc: str,
        last_synced_at_utc: str,
        icon_name: str | None = None,
    ) -> ConnectionMetadata:
        return ConnectionMetadata(
            alias,
            is_favorite,
            group_name,
            candidate.source,
            candidate.origin_identifier,
            candidate.source_fingerprint,
            imported_at_utc,
            last_synced_at_utc,
            icon_name,
        )

    def _show_error(self, title: str, exception: Exception) -> None:
        self.status_label.setText(f"{title}: {exception}")
        QMessageBox.critical(self, title, str(exception))

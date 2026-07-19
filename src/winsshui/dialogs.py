from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from winsshui.importers import ImportCandidate, WindowsClientImporter
from winsshui.diagnostics import SshDiagnostics
from winsshui.catalog import ConnectionCatalog
from winsshui.models import CommandSnippet, ConnectionItem, TerminalLaunchMode, WorkspaceItem
from winsshui.ssh_keys import SshKeyInfo, SshKeyManager
from winsshui.ssh_writer import SshConnectionDraft


class NewConnectionDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        initial: SshConnectionDraft | None = None,
        title: str = "Новое SSH-подключение",
        config_paths: tuple[Path, ...] = (),
        initial_config_path: Path | None = None,
        config_editable: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(680, 680)

        layout = QVBoxLayout(self)
        description = QLabel(
            "Подключение будет сохранено отдельным блоком Host в выбранном файле настроек SSH. "
            "Пароли приложение не хранит."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        basic_tab = QWidget()
        form = QFormLayout(basic_tab)
        form.setVerticalSpacing(10)
        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText("prod-web-01")
        self.hostname_edit = QLineEdit()
        self.hostname_edit.setPlaceholderText("10.20.1.15 или server.example.com")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("ubuntu")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.identity_edit = QLineEdit()
        self.identity_edit.setPlaceholderText("C:\\Users\\name\\.ssh\\id_ed25519")
        browse_key = QPushButton("Обзор…")
        browse_key.clicked.connect(self._browse_identity)
        identity_row = QHBoxLayout()
        identity_row.addWidget(self.identity_edit, 1)
        identity_row.addWidget(browse_key)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("bastion или user@bastion:22")
        self.group_edit = QLineEdit()
        self.group_edit.setPlaceholderText("Production/Web")
        self.favorite_check = QCheckBox("Добавить в избранное")
        self.config_combo = QComboBox()
        self.config_combo.setEditable(config_editable)
        for config_path in config_paths:
            self.config_combo.addItem(str(config_path), str(config_path))
        if initial_config_path is not None:
            index = self.config_combo.findData(str(initial_config_path))
            if index < 0:
                self.config_combo.addItem(str(initial_config_path), str(initial_config_path))
                index = self.config_combo.count() - 1
            self.config_combo.setCurrentIndex(index)

        form.addRow("Алиас *", self.alias_edit)
        form.addRow("Хост *", self.hostname_edit)
        form.addRow("Пользователь", self.user_edit)
        form.addRow("Порт", self.port_spin)
        form.addRow("Приватный ключ", identity_row)
        form.addRow("Промежуточный хост", self.proxy_edit)
        form.addRow("Папка", self.group_edit)
        if config_paths or initial_config_path is not None:
            form.addRow("Файл настроек", self.config_combo)
        form.addRow("", self.favorite_check)
        tabs.addTab(basic_tab, "Основное")

        network_tab = QWidget()
        network_form = QFormLayout(network_tab)
        network_form.setVerticalSpacing(10)
        self.connect_timeout_spin = self._optional_spin(300)
        self.keepalive_interval_spin = self._optional_spin(3600)
        self.keepalive_count_spin = self._optional_spin(100)
        self.forward_agent_combo = self._optional_boolean_combo()
        self.compression_combo = self._optional_boolean_combo()
        network_form.addRow("Тайм-аут подключения, сек.", self.connect_timeout_spin)
        network_form.addRow("Интервал проверки связи, сек.", self.keepalive_interval_spin)
        network_form.addRow("Допустимо пропусков связи", self.keepalive_count_spin)
        network_form.addRow("Перенаправление агента", self.forward_agent_combo)
        network_form.addRow("Сжатие", self.compression_combo)
        tabs.addTab(network_tab, "Сеть")

        tunnels_tab = QWidget()
        tunnels_layout = QVBoxLayout(tunnels_tab)
        tunnel_help = QLabel(
            "По одному правилу в строке. Локальный/удалённый туннель: "
            "[адрес_привязки:]порт хост:порт. SOCKS-туннель: [адрес_привязки:]порт."
        )
        tunnel_help.setWordWrap(True)
        tunnels_layout.addWidget(tunnel_help)
        self.local_forwards_edit = QPlainTextEdit()
        self.local_forwards_edit.setPlaceholderText("127.0.0.1:5432 db.internal:5432")
        self.remote_forwards_edit = QPlainTextEdit()
        self.remote_forwards_edit.setPlaceholderText("8080 127.0.0.1:8080")
        self.dynamic_forwards_edit = QPlainTextEdit()
        self.dynamic_forwards_edit.setPlaceholderText("127.0.0.1:1080")
        tunnels_layout.addWidget(QLabel("Локальные (LocalForward)"))
        tunnels_layout.addWidget(self.local_forwards_edit)
        tunnels_layout.addWidget(QLabel("Удалённые (RemoteForward)"))
        tunnels_layout.addWidget(self.remote_forwards_edit)
        tunnels_layout.addWidget(QLabel("SOCKS (DynamicForward)"))
        tunnels_layout.addWidget(self.dynamic_forwards_edit)
        tabs.addTab(tunnels_tab, "Туннели")

        startup_tab = QWidget()
        startup_form = QFormLayout(startup_tab)
        self.request_tty_combo = QComboBox()
        self.request_tty_combo.addItem("По умолчанию", None)
        for label, value in (
            ("Автоматически", "auto"),
            ("Да", "yes"),
            ("Принудительно", "force"),
            ("Нет", "no"),
        ):
            self.request_tty_combo.addItem(label, value)
        self.remote_command_edit = QLineEdit()
        self.remote_command_edit.setPlaceholderText("cd /srv/app && exec bash")
        startup_form.addRow("Псевдотерминал", self.request_tty_combo)
        startup_form.addRow("Команда после подключения", self.remote_command_edit)
        tabs.addTab(startup_tab, "Запуск")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if initial is not None:
            self._populate(initial)

    def draft(self) -> SshConnectionDraft:
        draft = SshConnectionDraft(
            alias=self.alias_edit.text().strip(),
            hostname=self.hostname_edit.text().strip(),
            user=self.user_edit.text().strip() or None,
            port=self.port_spin.value(),
            identity_file=self.identity_edit.text().strip() or None,
            proxy_jump=self.proxy_edit.text().strip() or None,
            connect_timeout=self._optional_spin_value(self.connect_timeout_spin),
            server_alive_interval=self._optional_spin_value(self.keepalive_interval_spin),
            server_alive_count_max=self._optional_spin_value(self.keepalive_count_spin),
            forward_agent=self.forward_agent_combo.currentData(),
            compression=self.compression_combo.currentData(),
            request_tty=self.request_tty_combo.currentData(),
            remote_command=self.remote_command_edit.text().strip() or None,
            local_forwards=self._lines(self.local_forwards_edit),
            remote_forwards=self._lines(self.remote_forwards_edit),
            dynamic_forwards=self._lines(self.dynamic_forwards_edit),
            group_name=self.group_edit.text().strip() or None,
            is_favorite=self.favorite_check.isChecked(),
        )
        draft.validate()
        return draft

    def target_config_path(self) -> Path | None:
        text = self.config_combo.currentText().strip()
        return Path(text).expanduser().resolve() if text else None

    def _validate_and_accept(self) -> None:
        try:
            self.draft()
        except ValueError as exception:
            QMessageBox.warning(self, "Проверьте подключение", str(exception))
            return
        self.accept()

    def _browse_identity(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Выберите приватный ключ OpenSSH",
            str(Path.home() / ".ssh"),
            "Ключи OpenSSH (*);;Все файлы (*)",
        )
        if filename:
            self.identity_edit.setText(filename)

    def _populate(self, draft: SshConnectionDraft) -> None:
        self.alias_edit.setText(draft.alias)
        self.hostname_edit.setText(draft.hostname)
        self.user_edit.setText(draft.user or "")
        self.port_spin.setValue(draft.port)
        self.identity_edit.setText(draft.identity_file or "")
        self.proxy_edit.setText(draft.proxy_jump or "")
        self.group_edit.setText(draft.group_name or "")
        self.favorite_check.setChecked(draft.is_favorite)
        self._set_optional_spin(self.connect_timeout_spin, draft.connect_timeout)
        self._set_optional_spin(self.keepalive_interval_spin, draft.server_alive_interval)
        self._set_optional_spin(self.keepalive_count_spin, draft.server_alive_count_max)
        self._set_combo_data(self.forward_agent_combo, draft.forward_agent)
        self._set_combo_data(self.compression_combo, draft.compression)
        self._set_combo_data(self.request_tty_combo, draft.request_tty)
        self.remote_command_edit.setText(draft.remote_command or "")
        self.local_forwards_edit.setPlainText("\n".join(draft.local_forwards))
        self.remote_forwards_edit.setPlainText("\n".join(draft.remote_forwards))
        self.dynamic_forwards_edit.setPlainText("\n".join(draft.dynamic_forwards))

    @staticmethod
    def _optional_spin(maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(-1, maximum)
        spin.setSpecialValueText("По умолчанию")
        spin.setValue(-1)
        return spin

    @staticmethod
    def _optional_spin_value(spin: QSpinBox) -> int | None:
        return None if spin.value() < 0 else spin.value()

    @staticmethod
    def _set_optional_spin(spin: QSpinBox, value: int | None) -> None:
        spin.setValue(-1 if value is None else value)

    @staticmethod
    def _optional_boolean_combo() -> QComboBox:
        combo = QComboBox()
        combo.addItem("По умолчанию", None)
        combo.addItem("Да", True)
        combo.addItem("Нет", False)
        return combo

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(index, 0))

    @staticmethod
    def _lines(editor: QPlainTextEdit) -> tuple[str, ...]:
        return tuple(line.strip() for line in editor.toPlainText().splitlines() if line.strip())


class DiagnosticsDialog(QDialog):
    def __init__(
        self,
        diagnostics: SshDiagnostics,
        alias: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.diagnostics = diagnostics
        self.alias = alias
        self._process: QProcess | None = None
        self._timer: QTimer | None = None
        self._phase = ""
        self._timed_out = False
        self.setWindowTitle(f"Диагностика SSH — {alias}")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Проверка не запрашивает пароль: BatchMode позволяет проверить сеть, host key и "
            "доступную неинтерактивную аутентификацию."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Проверить снова")
        self.refresh_button.clicked.connect(self.start)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self._close_dialog)
        actions.addWidget(self.refresh_button)
        actions.addStretch()
        actions.addWidget(close_button)
        layout.addLayout(actions)
        QTimer.singleShot(0, self.start)

    def start(self) -> None:
        self.output.clear()
        self.refresh_button.setEnabled(False)
        self._append("Проверка SSH-подключения…")
        try:
            program, arguments = self.diagnostics.connection_command(self.alias)
        except (FileNotFoundError, ValueError) as exception:
            self._append(f"ОШИБКА: {exception}")
            self._run_agent()
            return
        self._start_process("connection", program, arguments, 12000)

    def _run_agent(self) -> None:
        self._append("\nПроверка ssh-agent…")
        try:
            program, arguments = self.diagnostics.agent_command()
        except FileNotFoundError as exception:
            self._append(f"ОШИБКА: {exception}")
            self.refresh_button.setEnabled(True)
            return
        self._start_process("agent", program, arguments, 5000)

    def _start_process(
        self,
        phase: str,
        program: str,
        arguments: list[str],
        timeout_ms: int,
    ) -> None:
        process = QProcess(self)
        timer = QTimer(process)
        timer.setSingleShot(True)
        self._process = process
        self._timer = timer
        self._phase = phase
        self._timed_out = False
        process.setProgram(program)
        process.setArguments(arguments)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        timer.timeout.connect(self._timeout)
        process.start()
        timer.start(timeout_ms)

    def _finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        process = self._process
        if process is None:
            return
        if self._timer:
            self._timer.stop()
        output = (
            bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
            + bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        ).strip()
        phase = self._phase
        timed_out = self._timed_out
        self._process = None
        process.deleteLater()
        if phase == "connection":
            assessment = self.diagnostics.assess_connection(exit_code, output, timed_out)
            self._append(f"{assessment.summary}\n{output}".rstrip())
            self._run_agent()
        else:
            assessment = self.diagnostics.assess_agent(exit_code, output)
            self._append(f"{assessment.summary}\n{output}".rstrip())
            self.refresh_button.setEnabled(True)

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart or self._process is None:
            return
        phase = self._phase
        self._append(f"Не удалось запустить {self._process.program()}")
        self._process.deleteLater()
        self._process = None
        if phase == "connection":
            self._run_agent()
        else:
            self.refresh_button.setEnabled(True)

    def _timeout(self) -> None:
        if self._process is not None:
            self._timed_out = True
            self._process.kill()

    def _append(self, text: str) -> None:
        self.output.appendPlainText(text)

    def _close_dialog(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(300)
        self._process = None
        self.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(300)
        self._process = None
        super().closeEvent(event)


class CommandSnippetsDialog(QDialog):
    def __init__(
        self,
        catalog: ConnectionCatalog,
        alias: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.alias = alias
        self._editing_id: int | None = None
        self.setWindowTitle("Командные сниппеты")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        description = QLabel(
            "Сниппет запускается как удалённая команда через ssh.exe. "
            "Пароли и локальные команды здесь не выполняются."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Название", "Область", "Команда"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._load_selection)
        layout.addWidget(self.table, 1)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Например, Последние ошибки nginx")
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText("journalctl -u nginx -n 100 --no-pager")
        self.global_check = QCheckBox("Доступна для всех подключений")
        self.global_check.setChecked(alias is None)
        self.global_check.setEnabled(alias is not None)
        form.addRow("Название", self.name_edit)
        form.addRow("Команда", self.command_edit)
        form.addRow("", self.global_check)
        layout.addLayout(form)

        actions = QHBoxLayout()
        new_button = QPushButton("Новый")
        new_button.clicked.connect(self._clear_form)
        save_button = QPushButton("Сохранить")
        save_button.setObjectName("accentButton")
        save_button.clicked.connect(self._save)
        delete_button = QPushButton("Удалить")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self._delete)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.accept)
        actions.addWidget(new_button)
        actions.addWidget(save_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self._reload()

    def _reload(self) -> None:
        snippets = self.catalog.get_command_snippets(self.alias)
        self.table.setRowCount(len(snippets))
        for row, snippet in enumerate(snippets):
            name = QTableWidgetItem(snippet.name)
            name.setData(Qt.ItemDataRole.UserRole, snippet)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(snippet.alias or "Все подключения"))
            self.table.setItem(row, 2, QTableWidgetItem(snippet.command))

    def _selected(self) -> CommandSnippet | None:
        row = self.table.currentRow()
        snippet = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None
        return snippet if isinstance(snippet, CommandSnippet) else None

    def _load_selection(self) -> None:
        snippet = self._selected()
        if not snippet:
            return
        self._editing_id = snippet.id
        self.name_edit.setText(snippet.name)
        self.command_edit.setText(snippet.command)
        self.global_check.setChecked(snippet.alias is None)

    def _clear_form(self) -> None:
        self._editing_id = None
        self.table.clearSelection()
        self.name_edit.clear()
        self.command_edit.clear()
        self.global_check.setChecked(self.alias is None)
        self.name_edit.setFocus()

    def _save(self) -> None:
        target_alias = None if self.global_check.isChecked() else self.alias
        try:
            self.catalog.save_command_snippet(
                self.name_edit.text(),
                self.command_edit.text(),
                target_alias,
                self._editing_id,
            )
        except (ValueError, LookupError, sqlite3.Error) as exception:
            QMessageBox.warning(self, "Не удалось сохранить команду", str(exception))
            return
        self._clear_form()
        self._reload()

    def _delete(self) -> None:
        snippet = self._selected()
        if not snippet:
            return
        if QMessageBox.question(self, "Удалить команду", f"Удалить «{snippet.name}»?") != QMessageBox.StandardButton.Yes:
            return
        self.catalog.delete_command_snippet(snippet.id)
        self._clear_form()
        self._reload()


class SshKeyManagerDialog(QDialog):
    def __init__(self, manager: SshKeyManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("SSH-ключи и ssh-agent")
        self.resize(820, 480)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Ключи читаются из ~/.ssh. Создание и добавление в агент открываются в "
            "Windows Terminal, чтобы passphrase не попадала в приложение."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Имя", "Тип", "Отпечаток", "Приватный", "В агенте"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        create_button = QPushButton("Создать ключ…")
        create_button.clicked.connect(self._create)
        copy_button = QPushButton("Копировать публичный ключ")
        copy_button.clicked.connect(self._copy_public)
        add_button = QPushButton("Добавить в агент")
        add_button.clicked.connect(self._add_to_agent)
        remove_button = QPushButton("Удалить из агента")
        remove_button.clicked.connect(self._remove_from_agent)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self._reload)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.accept)
        for button in (create_button, copy_button, add_button, remove_button, refresh_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self._reload()

    def _reload(self) -> None:
        try:
            keys = self.manager.list_keys()
        except (OSError, subprocess.SubprocessError) as exception:
            QMessageBox.warning(self, "Не удалось прочитать ключи", str(exception))
            keys = []
        self.table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            name = QTableWidgetItem(key.name)
            name.setData(Qt.ItemDataRole.UserRole, key)
            self.table.setItem(row, 0, name)
            values = (key.key_type, key.fingerprint, "Да" if key.private_path else "Нет", "Да" if key.loaded_in_agent else "Нет")
            for column, value in enumerate(values, start=1):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def _selected(self) -> SshKeyInfo | None:
        row = self.table.currentRow()
        key = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None
        return key if isinstance(key, SshKeyInfo) else None

    def _create(self) -> None:
        name, accepted = QInputDialog.getText(self, "Новый SSH-ключ", "Имя файла:", text="id_ed25519")
        if not accepted:
            return
        key_type, accepted = QInputDialog.getItem(self, "Тип ключа", "Алгоритм:", ["ED25519", "RSA 4096"], 0, False)
        if not accepted:
            return
        comment, accepted = QInputDialog.getText(self, "Комментарий", "Комментарий ключа:")
        if not accepted:
            return
        try:
            self.manager.launch_create_key(name, "rsa" if key_type.startswith("RSA") else "ed25519", comment)
        except (OSError, ValueError) as exception:
            QMessageBox.warning(self, "Не удалось создать ключ", str(exception))
            return
        QMessageBox.information(self, "Создание ключа", "Открыт Windows Terminal. После завершения нажмите «Обновить».")

    def _copy_public(self) -> None:
        key = self._selected()
        if not key or not key.public_path:
            return
        try:
            QApplication.clipboard().setText(key.public_path.read_text(encoding="utf-8").strip())
        except OSError as exception:
            QMessageBox.warning(self, "Не удалось прочитать публичный ключ", str(exception))

    def _add_to_agent(self) -> None:
        key = self._selected()
        if not key:
            return
        try:
            self.manager.launch_add_to_agent(key)
        except (OSError, ValueError) as exception:
            QMessageBox.warning(self, "Не удалось открыть ssh-add", str(exception))

    def _remove_from_agent(self) -> None:
        key = self._selected()
        if not key:
            return
        try:
            self.manager.remove_from_agent(key)
            self._reload()
        except (OSError, RuntimeError) as exception:
            QMessageBox.warning(self, "Не удалось удалить ключ из агента", str(exception))


class WorkspaceDialog(QDialog):
    def __init__(
        self,
        catalog: ConnectionCatalog,
        connections: list[ConnectionItem],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.connections = connections
        self.launch_items: tuple[WorkspaceItem, ...] = ()
        self.workspaces = self.catalog.get_workspaces()
        self.setWindowTitle("Рабочие пространства")
        self.resize(720, 580)

        layout = QVBoxLayout(self)
        selector_row = QHBoxLayout()
        self.workspace_combo = QComboBox()
        self.workspace_combo.addItem("Новое пространство", None)
        for workspace in self.workspaces:
            self.workspace_combo.addItem(workspace.name, workspace.id)
        self.workspace_combo.currentIndexChanged.connect(self._load_selected)
        new_button = QPushButton("Новое")
        new_button.clicked.connect(self._new_workspace)
        selector_row.addWidget(QLabel("Сохранённые:"))
        selector_row.addWidget(self.workspace_combo, 1)
        selector_row.addWidget(new_button)
        layout.addLayout(selector_row)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Например, Production")
        layout.addWidget(self.name_edit)

        self.table = QTableWidget(len(connections), 3)
        self.table.setHorizontalHeaderLabels(["Открыть", "Подключение", "Расположение"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, connection in enumerate(connections):
            selected = QTableWidgetItem()
            selected.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            selected.setCheckState(Qt.CheckState.Unchecked)
            selected.setData(Qt.ItemDataRole.UserRole, connection.alias)
            alias_item = QTableWidgetItem(connection.alias)
            alias_item.setFlags(alias_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            mode_combo = QComboBox()
            mode_combo.addItem("Новая вкладка", TerminalLaunchMode.NEW_TAB)
            mode_combo.addItem("Панель справа", TerminalLaunchMode.SPLIT_RIGHT)
            self.table.setItem(row, 0, selected)
            self.table.setItem(row, 1, alias_item)
            self.table.setCellWidget(row, 2, mode_combo)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        save_button = QPushButton("Сохранить")
        save_button.clicked.connect(self._save)
        delete_button = QPushButton("Удалить")
        delete_button.clicked.connect(self._delete)
        launch_button = QPushButton("Запустить")
        launch_button.setObjectName("accentButton")
        launch_button.clicked.connect(self._launch)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.reject)
        actions.addWidget(save_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        actions.addWidget(launch_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def _collect(self) -> tuple[WorkspaceItem, ...]:
        result: list[WorkspaceItem] = []
        for row in range(self.table.rowCount()):
            selected = self.table.item(row, 0)
            if selected.checkState() != Qt.CheckState.Checked:
                continue
            mode_combo = self.table.cellWidget(row, 2)
            mode = (
                mode_combo.currentData()
                if isinstance(mode_combo, QComboBox)
                else TerminalLaunchMode.NEW_TAB
            )
            result.append(WorkspaceItem(selected.data(Qt.ItemDataRole.UserRole), mode))
        if result:
            result[0] = WorkspaceItem(result[0].alias, TerminalLaunchMode.NEW_TAB)
        return tuple(result)

    def _save(self) -> None:
        try:
            workspace = self.catalog.save_workspace(self.name_edit.text(), self._collect())
        except (ValueError, sqlite3.Error) as exception:
            QMessageBox.warning(self, "Не удалось сохранить пространство", str(exception))
            return
        self.workspaces = self.catalog.get_workspaces()
        existing_index = self.workspace_combo.findData(workspace.id)
        if existing_index < 0:
            self.workspace_combo.addItem(workspace.name, workspace.id)
            existing_index = self.workspace_combo.count() - 1
        self.workspace_combo.setCurrentIndex(existing_index)

    def _launch(self) -> None:
        items = self._collect()
        if not items:
            QMessageBox.warning(self, "Рабочее пространство", "Выберите хотя бы одно подключение")
            return
        if self.name_edit.text().strip():
            try:
                self.catalog.save_workspace(self.name_edit.text(), items)
            except (ValueError, sqlite3.Error) as exception:
                QMessageBox.warning(self, "Не удалось сохранить пространство", str(exception))
                return
        self.launch_items = items
        self.accept()

    def _delete(self) -> None:
        workspace_id = self.workspace_combo.currentData()
        if workspace_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить рабочее пространство",
            f"Удалить «{self.workspace_combo.currentText()}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.catalog.delete_workspace(int(workspace_id))
        self.workspace_combo.removeItem(self.workspace_combo.currentIndex())
        self._new_workspace()

    def _new_workspace(self) -> None:
        self.workspace_combo.setCurrentIndex(0)
        self.name_edit.clear()
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
            mode_combo = self.table.cellWidget(row, 2)
            if isinstance(mode_combo, QComboBox):
                mode_combo.setCurrentIndex(0)

    def _load_selected(self, _index: int) -> None:
        workspace_id = self.workspace_combo.currentData()
        workspace = next(
            (workspace for workspace in self.workspaces if workspace.id == workspace_id),
            None,
        )
        if workspace is None:
            self.name_edit.clear()
            return
        self.name_edit.setText(workspace.name)
        items = {item.alias.casefold(): item for item in workspace.items}
        for row in range(self.table.rowCount()):
            selected = self.table.item(row, 0)
            item = items.get(str(selected.data(Qt.ItemDataRole.UserRole)).casefold())
            selected.setCheckState(Qt.CheckState.Checked if item else Qt.CheckState.Unchecked)
            mode_combo = self.table.cellWidget(row, 2)
            if isinstance(mode_combo, QComboBox):
                index = mode_combo.findData(item.mode if item else TerminalLaunchMode.NEW_TAB)
                mode_combo.setCurrentIndex(max(index, 0))


class ImportConnectionsDialog(QDialog):
    def __init__(self, importer: WindowsClientImporter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.importer = importer
        self._candidate_keys: set[tuple[str, str, str, int]] = set()
        self.setWindowTitle("Импорт SSH-подключений")
        self.resize(1000, 560)

        layout = QVBoxLayout(self)
        description = QLabel(
            "Автоматически читаются WinSCP и PuTTY из Registry, а также известные INI/XML-файлы "
            "MTPuTTY, SuperPuTTY, FileZilla SFTP и mRemoteNG. Пароли не импортируются."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        actions = QHBoxLayout()
        choose_file = QPushButton("Добавить INI/XML-файл…")
        choose_file.clicked.connect(self._choose_file)
        select_all = QPushButton("Выбрать все")
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        select_none = QPushButton("Снять выбор")
        select_none.clicked.connect(lambda: self._set_all_checked(False))
        actions.addWidget(choose_file)
        actions.addWidget(select_all)
        actions.addWidget(select_none)
        actions.addStretch()
        layout.addLayout(actions)

        folder_actions = QHBoxLayout()
        folder_label = QLabel("Папка для выбранных:")
        self.destination_folder_edit = QLineEdit()
        self.destination_folder_edit.setPlaceholderText("Например, Импорт/Рабочие")
        apply_folder = QPushButton("Назначить выбранным")
        apply_folder.clicked.connect(self._apply_folder_to_checked)
        folder_actions.addWidget(folder_label)
        folder_actions.addWidget(self.destination_folder_edit, 1)
        folder_actions.addWidget(apply_folder)
        layout.addLayout(folder_actions)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Импорт",
                "Алиас",
                "Папка",
                "Хост",
                "Пользователь",
                "Порт",
                "Источник",
                "Предупреждение",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.EditKeyPressed
            | QTableWidget.EditTrigger.SelectedClicked
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for column in (1, 2, 3, 4, 6):
            header.setSectionResizeMode(column, header.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Импортировать выбранные")
        buttons.accepted.connect(self._accept_if_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        result = self.importer.scan_known_sources()
        self._add_candidates(result.candidates)
        warning_text = "\n".join(result.warnings)
        self.status_label.setText(
            f"Найдено подключений: {self.table.rowCount()}"
            + (f"\nПредупреждения сканирования: {warning_text}" if warning_text else "")
        )

    def selected_candidates(self) -> list[ImportCandidate]:
        result: list[ImportCandidate] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.checkState() == Qt.CheckState.Checked:
                candidate = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(candidate, ImportCandidate):
                    folder = self.table.item(row, 2).text().strip() or candidate.source
                    result.append(replace(candidate, group_name=folder))
        return result

    def _add_candidates(self, candidates: tuple[ImportCandidate, ...] | list[ImportCandidate]) -> None:
        for candidate in candidates:
            key = (candidate.source, candidate.name, candidate.hostname, candidate.port)
            if key in self._candidate_keys:
                continue
            self._candidate_keys.add(key)
            row = self.table.rowCount()
            self.table.insertRow(row)
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checkbox.setCheckState(Qt.CheckState.Checked)
            checkbox.setData(Qt.ItemDataRole.UserRole, candidate)
            self.table.setItem(row, 0, checkbox)
            values = (
                candidate.alias,
                candidate.group_name or candidate.source,
                candidate.hostname,
                candidate.user or "",
                str(candidate.port),
                candidate.source,
                candidate.warning or "",
            )
            for column, value in enumerate(values, start=1):
                value_item = QTableWidgetItem(value)
                if column != 2:
                    value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, value_item)

    def _choose_file(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Выберите экспорт или конфигурацию клиента",
            str(Path.home()),
            "Поддерживаемые файлы (*.ini *.xml *.config);;Все файлы (*)",
        )
        if not filename:
            return
        try:
            candidates = self.importer.import_file(Path(filename))
        except Exception as exception:
            QMessageBox.warning(self, "Файл не импортирован", str(exception))
            return
        self._add_candidates(candidates)
        self.status_label.setText(f"Найдено подключений: {self.table.rowCount()}")

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)

    def _apply_folder_to_checked(self) -> None:
        folder = self.destination_folder_edit.text().replace("\\", "/").strip("/ ")
        if not folder:
            QMessageBox.information(self, "Папка не указана", "Введите имя папки назначения")
            return
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked:
                self.table.item(row, 2).setText(folder)

    def _accept_if_selected(self) -> None:
        if not self.selected_candidates():
            QMessageBox.information(self, "Ничего не выбрано", "Выберите хотя бы одно подключение")
            return
        self.accept()

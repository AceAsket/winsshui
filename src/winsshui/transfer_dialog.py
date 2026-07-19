from __future__ import annotations

import posixpath
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from winsshui.transfers import OpenSshTransferManager, RemoteEntry, TransferCommand


class SftpBrowserDialog(QDialog):
    def __init__(
        self,
        manager: OpenSshTransferManager,
        alias: str,
        initial_path: str | None = None,
        askpass_path: str | None = None,
        credential_alias: str | None = None,
        save_path: Callable[[str], None] | None = None,
        open_winscp: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.alias = alias
        self.askpass_path = askpass_path
        self.credential_alias = credential_alias
        self.save_path = save_path
        self.open_winscp = open_winscp
        self._process: QProcess | None = None
        self._operation = ""
        self._fallback_command: TransferCommand | None = None
        self._legacy_mode = False
        self._using_legacy = False
        self.setWindowTitle(f"SFTP и SCP — {alias}")
        self.resize(880, 620)
        layout = QVBoxLayout(self)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Удалённый путь:"))
        self.path_edit = QLineEdit(initial_path or "/")
        self.path_edit.returnPressed.connect(self.refresh)
        path_row.addWidget(self.path_edit, 1)
        up_button = QPushButton("Вверх")
        up_button.clicked.connect(self._up)
        refresh_button = QPushButton("Обновить")
        refresh_button.clicked.connect(self.refresh)
        path_row.addWidget(up_button)
        path_row.addWidget(refresh_button)
        layout.addLayout(path_row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Имя", "Тип", "Размер"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda _item, _column: self._open_selected())
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        upload_file = QPushButton("Загрузить файл (SCP)…")
        upload_file.clicked.connect(self._upload_file)
        upload_folder = QPushButton("Загрузить папку (SCP)…")
        upload_folder.clicked.connect(self._upload_folder)
        download = QPushButton("Скачать выбранное (SCP)…")
        download.clicked.connect(self._download)
        copy_path = QPushButton("Копировать путь")
        copy_path.clicked.connect(self._copy_path)
        for button in (upload_file, upload_folder, download, copy_path):
            actions.addWidget(button)
        if open_winscp:
            winscp = QPushButton("Открыть в WinSCP")
            winscp.clicked.connect(lambda: open_winscp(self.path_edit.text()))
            actions.addWidget(winscp)
        actions.addStretch()
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)
        self.refresh()

    def refresh(self) -> None:
        try:
            fallback = None
            if self._legacy_mode or not self.manager.sftp_path:
                self._legacy_mode = True
                command = self.manager.fallback_list_command(self.alias, self.path_edit.text())
            else:
                command = self.manager.list_command(self.alias, self.path_edit.text())
                try:
                    fallback = self.manager.fallback_list_command(
                        self.alias, self.path_edit.text()
                    )
                except FileNotFoundError:
                    pass
        except (OSError, ValueError) as exception:
            QMessageBox.warning(self, "SFTP", str(exception))
            return
        self._run(command, "list", fallback, self._legacy_mode)

    def _run(
        self,
        command: TransferCommand,
        operation: str,
        fallback: TransferCommand | None = None,
        using_legacy: bool = False,
    ) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            return
        process = QProcess(self)
        self._process = process
        self._operation = operation
        self._fallback_command = fallback
        self._using_legacy = using_legacy
        process.setProgram(command.program)
        process.setArguments(list(command.arguments))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if self.askpass_path and self.credential_alias:
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("SSH_ASKPASS", self.askpass_path)
            environment.insert("SSH_ASKPASS_REQUIRE", "force")
            environment.insert("WINSSHUI_CREDENTIAL_ALIAS", self.credential_alias)
            process.setProcessEnvironment(environment)
        process.started.connect(
            lambda: (process.write(command.standard_input), process.closeWriteChannel())
            if command.standard_input
            else None
        )
        process.finished.connect(lambda code, _status: self._finished(process, code))
        protocol = "SSH / классический SCP" if using_legacy else "SFTP / SCP"
        self.log.setPlainText(f"{operation}: выполняется через {protocol}…")
        process.start()

    def _finished(self, process: QProcess, exit_code: int) -> None:
        if process is not self._process:
            return
        output = bytes(process.readAll()).decode("utf-8", errors="replace").strip()
        operation = self._operation
        fallback = self._fallback_command
        used_legacy = self._using_legacy
        self._process = None
        self._fallback_command = None
        process.deleteLater()
        if exit_code != 0:
            if fallback and self.manager.needs_legacy_fallback(output):
                self._legacy_mode = True
                self._run(fallback, operation, using_legacy=True)
                return
            self.log.setPlainText(output or f"Процесс завершился с кодом {exit_code}")
            return
        if operation == "list":
            self._show_entries(self.manager.parse_listing(output))
            normalized = self.manager.normalize_remote_path(self.path_edit.text())
            self.path_edit.setText(normalized)
            if self.save_path:
                self.save_path(normalized)
            protocol = "SSH (SFTP на сервере отсутствует)" if used_legacy else "SFTP"
            self.log.setPlainText(f"{protocol}: показано объектов: {self.table.rowCount()}")
        else:
            protocol = "классический SCP" if used_legacy else "SCP"
            self.log.setPlainText(output or f"Передача через {protocol} завершена успешно")
            self.refresh()

    def _show_entries(self, entries: tuple[RemoteEntry, ...]) -> None:
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            name = QTableWidgetItem(entry.name)
            name.setData(Qt.ItemDataRole.UserRole, entry)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem("Папка" if entry.is_directory else "Файл"))
            self.table.setItem(row, 2, QTableWidgetItem("" if entry.size is None else str(entry.size)))

    def _selected(self) -> RemoteEntry | None:
        row = self.table.currentRow()
        value = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None
        return value if isinstance(value, RemoteEntry) else None

    def _open_selected(self) -> None:
        entry = self._selected()
        if entry and entry.is_directory:
            self.path_edit.setText(self.manager.join_remote_path(self.path_edit.text(), entry.name))
            self.refresh()

    def _up(self) -> None:
        current = self.manager.normalize_remote_path(self.path_edit.text())
        self.path_edit.setText(posixpath.dirname(current.rstrip("/")) or "/")
        self.refresh()

    def _upload_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Файл для загрузки")
        if selected:
            primary = self.manager.upload_command(
                self.alias, Path(selected), self.path_edit.text(), legacy=self._legacy_mode
            )
            fallback = None if self._legacy_mode else self.manager.upload_command(
                self.alias, Path(selected), self.path_edit.text(), legacy=True
            )
            self._run(primary, "upload", fallback, self._legacy_mode)

    def _upload_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Папка для загрузки")
        if selected:
            primary = self.manager.upload_command(
                self.alias, Path(selected), self.path_edit.text(), True, self._legacy_mode
            )
            fallback = None if self._legacy_mode else self.manager.upload_command(
                self.alias, Path(selected), self.path_edit.text(), True, True
            )
            self._run(primary, "upload", fallback, self._legacy_mode)

    def _download(self) -> None:
        entry = self._selected()
        if not entry:
            return
        selected = QFileDialog.getExistingDirectory(self, "Куда скачать")
        if selected:
            remote = self.manager.join_remote_path(self.path_edit.text(), entry.name)
            primary = self.manager.download_command(
                self.alias, remote, Path(selected), entry.is_directory, self._legacy_mode
            )
            fallback = None if self._legacy_mode else self.manager.download_command(
                self.alias, remote, Path(selected), entry.is_directory, True
            )
            self._run(primary, "download", fallback, self._legacy_mode)

    def _copy_path(self) -> None:
        entry = self._selected()
        path = (
            self.manager.join_remote_path(self.path_edit.text(), entry.name)
            if entry
            else self.path_edit.text()
        )
        QApplication.clipboard().setText(path)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(500)
        super().closeEvent(event)

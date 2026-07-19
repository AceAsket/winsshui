from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from winsshui.importers import ImportCandidate, WindowsClientImporter
from winsshui.ssh_writer import SshConnectionDraft


class NewConnectionDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новое SSH-подключение")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        description = QLabel(
            "Подключение будет сохранено отдельным Host-блоком в ~/.ssh/config. "
            "Пароли приложение не хранит."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
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

        form.addRow("Алиас *", self.alias_edit)
        form.addRow("Хост *", self.hostname_edit)
        form.addRow("Пользователь", self.user_edit)
        form.addRow("Порт", self.port_spin)
        form.addRow("Приватный ключ", identity_row)
        form.addRow("ProxyJump", self.proxy_edit)
        form.addRow("Папка", self.group_edit)
        form.addRow("", self.favorite_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def draft(self) -> SshConnectionDraft:
        draft = SshConnectionDraft(
            alias=self.alias_edit.text().strip(),
            hostname=self.hostname_edit.text().strip(),
            user=self.user_edit.text().strip() or None,
            port=self.port_spin.value(),
            identity_file=self.identity_edit.text().strip() or None,
            proxy_jump=self.proxy_edit.text().strip() or None,
            group_name=self.group_edit.text().strip() or None,
            is_favorite=self.favorite_check.isChecked(),
        )
        draft.validate()
        return draft

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
        self.destination_folder_edit.setPlaceholderText("Например, Imported/Production")
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

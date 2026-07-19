from __future__ import annotations

import time
from datetime import UTC, datetime

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from winsshui.catalog import ConnectionCatalog
from winsshui.diagnostics import SshDiagnostics
from winsshui.models import ConnectionHealth, ConnectionItem


class ConnectionHealthDialog(QDialog):
    parallelism = 4

    def __init__(
        self,
        catalog: ConnectionCatalog,
        diagnostics: SshDiagnostics,
        connections: list[ConnectionItem],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.diagnostics = diagnostics
        self.connections = connections
        self._pending: list[tuple[int, ConnectionItem]] = []
        self._running: dict[QProcess, tuple[int, ConnectionItem, float, QTimer]] = {}
        self._timed_out: set[QProcess] = set()
        self.setWindowTitle("Состояние SSH-подключений")
        self.resize(940, 590)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Проверка выполняет неинтерактивное SSH-подключение с BatchMode и не запрашивает пароль."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.table = QTableWidget(len(connections), 6)
        self.table.setHorizontalHeaderLabels(
            ["Подключение", "Адрес", "Состояние", "Задержка", "Последний успех", "Проверено"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().ResizeMode.Stretch)
        previous = catalog.get_connection_health()
        for row, connection in enumerate(connections):
            self.table.setItem(row, 0, QTableWidgetItem(connection.alias))
            self.table.setItem(row, 1, QTableWidgetItem(connection.host.display_endpoint))
            saved = previous.get(connection.alias.casefold())
            self.table.setItem(row, 2, QTableWidgetItem(saved.summary if saved else "Не проверено"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{saved.latency_ms} мс" if saved and saved.latency_ms else "—"))
            self.table.setItem(row, 4, QTableWidgetItem(self._local_time(saved.last_success_at_utc if saved else None)))
            self.table.setItem(row, 5, QTableWidgetItem(self._local_time(saved.checked_at_utc if saved else None)))
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.check_button = QPushButton("Проверить все")
        self.check_button.setObjectName("accentButton")
        self.check_button.clicked.connect(self.start)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(self.check_button)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.start()

    def start(self) -> None:
        if self._running:
            return
        self._pending = list(enumerate(self.connections))
        self.check_button.setEnabled(False)
        for row, _connection in self._pending:
            self.table.item(row, 2).setText("Ожидает проверки…")
        self._start_more()

    def _start_more(self) -> None:
        while self._pending and len(self._running) < self.parallelism:
            row, connection = self._pending.pop(0)
            try:
                program, arguments = self.diagnostics.connection_command(connection.alias)
            except (OSError, ValueError) as exception:
                self.table.item(row, 2).setText(str(exception))
                continue
            process = QProcess(self)
            timer = QTimer(process)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda current=process: self._timeout(current))
            process.setProgram(program)
            process.setArguments(arguments)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            process.finished.connect(
                lambda code, _status, current=process: self._finished(current, code)
            )
            self._running[process] = (row, connection, time.monotonic(), timer)
            self.table.item(row, 2).setText("Проверяется…")
            process.start()
            timer.start(10_000)
        if not self._pending and not self._running:
            self.check_button.setEnabled(True)

    def _timeout(self, process: QProcess) -> None:
        if process in self._running:
            self._timed_out.add(process)
            process.kill()

    def _finished(self, process: QProcess, exit_code: int) -> None:
        state = self._running.pop(process, None)
        if not state:
            return
        row, connection, started, timer = state
        timer.stop()
        latency = round((time.monotonic() - started) * 1000)
        output = bytes(process.readAll()).decode("utf-8", errors="replace")
        timed_out = process in self._timed_out
        self._timed_out.discard(process)
        assessment = self.diagnostics.assess_connection(exit_code, output, timed_out)
        now = datetime.now(UTC).isoformat()
        previous = self.catalog.get_connection_health().get(connection.alias.casefold())
        last_success = now if assessment.level == "ok" else (
            previous.last_success_at_utc if previous else None
        )
        health = ConnectionHealth(
            connection.alias,
            now,
            assessment.level,
            assessment.summary,
            latency,
            last_success,
        )
        self.catalog.save_connection_health(health)
        status = self.table.item(row, 2)
        status.setText(assessment.summary)
        status.setForeground(
            Qt.GlobalColor.darkGreen
            if assessment.level == "ok"
            else Qt.GlobalColor.darkYellow
            if assessment.level == "warning"
            else Qt.GlobalColor.red
        )
        self.table.item(row, 3).setText(f"{latency} мс")
        self.table.item(row, 4).setText(self._local_time(last_success))
        self.table.item(row, 5).setText(self._local_time(now))
        process.deleteLater()
        self._start_more()

    @staticmethod
    def _local_time(value: str | None) -> str:
        if not value:
            return "—"
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%d.%m.%Y %H:%M:%S")
        except ValueError:
            return value

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        for process in tuple(self._running):
            process.kill()
        super().closeEvent(event)

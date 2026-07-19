from __future__ import annotations

import logging
import os
import platform
import re
import sys
import zipfile
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from winsshui import __version__


_SECRET_PATTERNS = (
    re.compile(r"(?i)(password|passphrase)(\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(sftp|ssh)://([^:@/\s]+):([^@/\s]+)@"),
)


def redact_secrets(text: str) -> str:
    result = _SECRET_PATTERNS[0].sub(r"\1\2<скрыто>", text)
    return _SECRET_PATTERNS[1].sub(r"\1://\2:<скрыто>@", result)


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


def configure_logging(app_data_directory: Path) -> Path:
    log_directory = app_data_directory.resolve() / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "winsshui.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.addFilter(_RedactingFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in tuple(root.handlers):
        root.removeHandler(existing)
        existing.close()
    root.addHandler(handler)
    logging.getLogger(__name__).info(
        "WinSSH UI %s started; Python %s; Windows %s",
        __version__,
        platform.python_version(),
        platform.platform(),
    )
    return log_path


def install_exception_logger() -> None:
    previous_hook = sys.excepthook

    def log_exception(exception_type: type[BaseException], exception: BaseException, traceback: object) -> None:
        logging.getLogger("winsshui.unhandled").critical(
            "Unhandled exception",
            exc_info=(exception_type, exception, traceback),
        )
        previous_hook(exception_type, exception, traceback)

    sys.excepthook = log_exception


def export_diagnostics(log_path: Path, destination: Path) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = "\n".join(
        (
            f"WinSSH UI: {__version__}",
            f"Created UTC: {datetime.now(UTC).isoformat()}",
            f"Windows: {platform.platform()}",
            f"Python: {platform.python_version()}",
            f"Executable: {Path(sys.executable).name}",
            f"Frozen build: {bool(getattr(sys, 'frozen', False))}",
            f"OpenSSH: {os.environ.get('WINDIR', 'Windows')} feature / PATH detection in application log",
            "",
            "SSH config, keys, passwords and known_hosts are not collected automatically.",
            "The application log can contain connection aliases or addresses; review it before sharing.",
        )
    )
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("system-report.txt", report)
        if log_path.is_file():
            archive.writestr(
                "winsshui.log",
                redact_secrets(log_path.read_text(encoding="utf-8", errors="replace")),
            )
    return destination

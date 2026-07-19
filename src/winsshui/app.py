from __future__ import annotations

import os
import sys
import logging
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from winsshui import __version__
from winsshui.main_window import MainWindow
from winsshui.logging_utils import configure_logging, install_exception_logger
from winsshui.resources import resource_path


def app_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return (Path(local_app_data) if local_app_data else Path.home() / ".local" / "share") / "WinSshUi"


def main() -> int:
    data_directory = app_data_directory()
    log_path = configure_logging(data_directory)
    install_exception_logger()
    application = QApplication(sys.argv)
    application.setApplicationName("WinSSH UI")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("WinSSH UI")
    qt_translator = QTranslator(application)
    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt_translator.load("qtbase_ru", translations_path):
        application.installTranslator(qt_translator)
    icon_path = resource_path("assets/AppIcon.ico")
    if icon_path.exists():
        application.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(data_directory, log_path=log_path)
    window.show()
    result = application.exec()
    logging.getLogger(__name__).info("WinSSH UI stopped with code %s", result)
    return result

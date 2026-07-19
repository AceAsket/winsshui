from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from winsshui import __version__
from winsshui.main_window import MainWindow
from winsshui.resources import resource_path


def app_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return (Path(local_app_data) if local_app_data else Path.home() / ".local" / "share") / "WinSshUi"


def main() -> int:
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

    window = MainWindow(app_data_directory())
    window.show()
    return application.exec()

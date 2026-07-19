# WinSSH UI

WinSSH UI — самостоятельный менеджер SSH-подключений для Windows, полностью
написанный на Python. Интерфейс построен на PySide6, локальный каталог — на
стандартном `sqlite3`, а сессии открываются в Windows Terminal через `wt.exe`.

## Возможности

- импорт конкретных `Host`-алиасов из `%USERPROFILE%\.ssh\config`;
- создание новых подключений прямо из интерфейса;
- импорт из WinSCP, PuTTY, MTPuTTY, SuperPuTTY, FileZilla SFTP и mRemoteNG;
- получение эффективных параметров через `ssh -G`;
- поиск по алиасу, адресу, пользователю и группе;
- избранное и пользовательские группы;
- древовидные папки с вложенными путями `Source/Folder/Subfolder`;
- история последних 100 запусков;
- открытие SSH в новой вкладке или правой split-панели Windows Terminal;
- передача аргументов процессам списком, без PowerShell/cmd и конкатенации строк.

OpenSSH остаётся источником истины: приложение запускает `ssh.exe <alias>`, а
разрешение `Include`, wildcard-блоков и системных настроек выполняет сам SSH.
Приватные ключи и пароли приложение не хранит.

## Создание и импорт

Кнопка **«Новое подключение»** создаёт отдельный `Host`-блок в OpenSSH config.
Перед изменением существующего файла создаётся резервная копия `config.bak`, а
запись выполняется атомарно.

Кнопка **«Импорт»** автоматически сканирует:

- PuTTY и WinSCP в `HKCU` Registry;
- стандартные расположения WinSCP INI, MTPuTTY и SuperPuTTY XML;
- FileZilla `sitemanager.xml` — только SFTP;
- незашифрованные SSH-узлы mRemoteNG.

Можно также выбрать произвольный `.ini`, `.xml` или `.config` файл. Перед
сохранением показывается таблица с флажками и редактируемой папкой назначения.
Можно массово назначить папку всем отмеченным строкам. Автоимпорт всегда
подписывает источник: `PuTTY`, `WinSCP`, `SuperPuTTY/<исходная папка>` и т. п.
Пароли игнорируются. Ключи `.ppk` нужно предварительно конвертировать в формат
OpenSSH через PuTTYgen.

## Запуск из исходников

Требуются Python 3.10+, Windows Terminal и OpenSSH Client.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m winsshui
```

## Тесты

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests\python -v
```

## Сборка EXE

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe build.py
```

Результат создаётся в `dist\WinSSH-UI.exe`. Это one-file сборка: Python на
целевом компьютере не требуется. При первом запуске распаковка Qt во временный
каталог может занять несколько секунд.

## Данные

- SSH-конфигурация: `%USERPROFILE%\.ssh\config`;
- метаданные приложения: `%LOCALAPPDATA%\WinSshUi\catalog.db`.

## Структура

- `src/winsshui` — всё приложение;
- `tests/python` — unit- и smoke-тесты;
- `winsshui.spec` — воспроизводимая конфигурация PyInstaller;
- `docs/architecture.md` — архитектурные границы и развитие.

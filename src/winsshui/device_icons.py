from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QIcon

from winsshui.resources import resource_path


DEVICE_ICON_OPTIONS: tuple[tuple[str, str], ...] = (
    ("server", "Сервер"),
    ("router", "Роутер"),
    ("switch", "Коммутатор"),
    ("firewall", "Межсетевой экран"),
    ("nas", "NAS / хранилище"),
    ("cloud", "Облачный сервер"),
    ("workstation", "Рабочая станция"),
    ("database", "База данных"),
    ("terminal", "Терминал / консоль"),
)

VALID_DEVICE_ICONS = frozenset(name for name, _label in DEVICE_ICON_OPTIONS)


def infer_device_icon(alias: str, hostname: str | None = None, group_name: str | None = None) -> str:
    text = " ".join(filter(None, (alias, hostname, group_name))).casefold()
    rules = (
        ("firewall", ("firewall", "pfsense", "opnsense", "fortigate", "fortinet", " fw-", "/fw")),
        ("router", ("router", "gateway", "mikrotik", "keenetic", "openwrt", "asus", " rt-", "/rt")),
        ("switch", ("switch", "catalyst", "aruba", "procurve", " sw-", "/sw")),
        ("nas", (" nas", "storage", "synology", "truenas", "qnap")),
        ("database", ("database", "postgres", "mysql", "mariadb", "mongodb", " db-", "-db", "/db")),
        ("cloud", ("cloud", " aws", "azure", "gcp", "digitalocean", " vps")),
        ("workstation", ("desktop", "workstation", "laptop", " pc-", "/pc")),
        ("terminal", ("console", "terminal", "shell", " tty")),
    )
    padded = f" {text}"
    for icon_name, markers in rules:
        if any(marker in padded for marker in markers):
            return icon_name
    return "server"


def resolve_device_icon(
    icon_name: str | None,
    alias: str,
    hostname: str | None = None,
    group_name: str | None = None,
) -> str:
    return icon_name if icon_name in VALID_DEVICE_ICONS else infer_device_icon(alias, hostname, group_name)


@lru_cache(maxsize=None)
def device_icon(icon_name: str) -> QIcon:
    name = icon_name if icon_name in VALID_DEVICE_ICONS else "server"
    return QIcon(str(resource_path(f"assets/device-icons/{name}.svg")))


@lru_cache(maxsize=1)
def folder_icon() -> QIcon:
    return QIcon(str(resource_path("assets/device-icons/folder.svg")))

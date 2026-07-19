from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


LATEST_RELEASE_API = "https://api.github.com/repos/AceAsket/winsshui/releases/latest"
RELEASE_ASSET_NAMES = ("WinSSH-UI-Setup.exe", "WinSSH-UI.exe")


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    tag_name: str
    title: str
    notes: str
    page_url: str
    download_url: str | None
    asset_digest: str | None
    asset_name: str | None


def version_parts(value: str) -> tuple[int, ...]:
    normalized = value.strip().removeprefix("v")
    match = re.fullmatch(r"(\d+(?:\.\d+)*)", normalized)
    if match is None:
        raise ValueError(f"Некорректная версия релиза: {value}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (3 - len(parts))


def is_newer_version(latest: str, current: str) -> bool:
    return version_parts(latest) > version_parts(current)


def parse_latest_release(payload: bytes | str | dict[str, Any]) -> ReleaseInfo:
    if isinstance(payload, bytes):
        data = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload
    if not isinstance(data, dict):
        raise ValueError("GitHub вернул неожиданный формат релиза")

    tag_name = _required_text(data, "tag_name")
    version_parts(tag_name)
    page_url = _https_url(_required_text(data, "html_url"), "страницы релиза")
    title = str(data.get("name") or tag_name).strip()
    notes = str(data.get("body") or "").strip()

    download_url: str | None = None
    asset_digest: str | None = None
    asset_name: str | None = None
    assets = data.get("assets")
    if isinstance(assets, list):
        for preferred_name in RELEASE_ASSET_NAMES:
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                if str(asset.get("name") or "").casefold() != preferred_name.casefold():
                    continue
                candidate = str(asset.get("browser_download_url") or "").strip()
                if candidate:
                    download_url = _https_url(candidate, "файла релиза")
                    digest = str(asset.get("digest") or "").strip()
                    asset_digest = digest or None
                    asset_name = preferred_name
                break
            if download_url:
                break

    return ReleaseInfo(
        version=tag_name.removeprefix("v"),
        tag_name=tag_name,
        title=title,
        notes=notes,
        page_url=page_url,
        download_url=download_url,
        asset_digest=asset_digest,
        asset_name=asset_name,
    )


def expected_sha256(digest: str | None) -> str | None:
    if not digest:
        return None
    match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", digest.strip())
    return match.group(1).lower() if match else None


def file_sha256(path: str) -> str:
    checksum = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def _required_text(data: dict[str, Any], field: str) -> str:
    value = str(data.get(field) or "").strip()
    if not value:
        raise ValueError(f"В ответе GitHub отсутствует поле {field}")
    return value


def _https_url(value: str, description: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError(f"Некорректный адрес {description}")
    return value

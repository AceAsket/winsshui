from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from dataclasses import dataclass


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_CREDENTIAL_BLOB_SIZE = 2560


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


@dataclass(frozen=True, slots=True)
class StoredCredential:
    username: str
    password: str


class WindowsCredentialStore:
    """Small Unicode wrapper around the Windows Credential Manager API."""

    def __init__(self, api: object | None = None) -> None:
        if api is None:
            if os.name != "nt":
                raise OSError("Windows Credential Manager доступен только в Windows")
            api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._api = api
        self._configure_api()

    @staticmethod
    def target_name(alias: str) -> str:
        normalized = alias.strip().casefold()
        if not normalized:
            raise ValueError("SSH-алиас не может быть пустым")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"WinSSHUI:ssh:{digest}"

    def save(self, alias: str, username: str | None, password: str) -> None:
        if not password:
            raise ValueError("Пароль не может быть пустым")
        blob = password.encode("utf-16-le")
        if len(blob) > MAX_CREDENTIAL_BLOB_SIZE:
            raise ValueError("Пароль слишком длинный для Windows Credential Manager")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _CREDENTIALW()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = self.target_name(alias)
        credential.Comment = "SSH password saved by WinSSH UI"
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = username or alias
        if not self._api.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self, alias: str) -> StoredCredential | None:
        pointer = ctypes.POINTER(_CREDENTIALW)()
        if not self._api.CredReadW(
            self.target_name(alias), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            error = ctypes.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise ctypes.WinError(error)
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return StoredCredential(credential.UserName or "", raw.decode("utf-16-le"))
        finally:
            self._api.CredFree(pointer)

    def contains(self, alias: str) -> bool:
        return self.read(alias) is not None

    def delete(self, alias: str) -> bool:
        if self._api.CredDeleteW(self.target_name(alias), CRED_TYPE_GENERIC, 0):
            return True
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return False
        raise ctypes.WinError(error)

    def rename(self, old_alias: str, new_alias: str) -> bool:
        if old_alias.casefold() == new_alias.casefold():
            return self.contains(old_alias)
        credential = self.read(old_alias)
        if credential is None:
            return False
        self.save(new_alias, credential.username, credential.password)
        self.delete(old_alias)
        return True

    def _configure_api(self) -> None:
        for name, argtypes, restype in (
            (
                "CredWriteW",
                [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD],
                wintypes.BOOL,
            ),
            (
                "CredReadW",
                [
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
                ],
                wintypes.BOOL,
            ),
            (
                "CredDeleteW",
                [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD],
                wintypes.BOOL,
            ),
            ("CredFree", [ctypes.c_void_p], None),
        ):
            function = getattr(self._api, name)
            function.argtypes = argtypes
            function.restype = restype

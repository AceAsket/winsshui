from __future__ import annotations

import re
from dataclasses import dataclass


_PUBLIC_KEY_TYPE = re.compile(
    r"^(?:ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com|"
    r"sk-ecdsa-sha2-nistp256@openssh\.com)$"
)

_INSTALL_SCRIPT = (
    'umask 077; mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh" && '
    'touch "$HOME/.ssh/authorized_keys" && chmod 600 "$HOME/.ssh/authorized_keys" && '
    'IFS= read -r key && { grep -qxF "$key" "$HOME/.ssh/authorized_keys" || '
    'printf "%s\\n" "$key" >> "$HOME/.ssh/authorized_keys"; }'
)

_VERIFY_SCRIPT = (
    'IFS= read -r key && grep -qxF "$key" "$HOME/.ssh/authorized_keys"'
)


@dataclass(frozen=True, slots=True)
class PublicKeyInstallCommand:
    program: str
    arguments: tuple[str, ...]
    standard_input: bytes


def normalize_public_key(value: str) -> str:
    key = value.strip()
    if not key or "\n" in key or "\r" in key or len(key) > 16_384:
        raise ValueError("Публичный ключ должен занимать одну непустую строку")
    parts = key.split()
    if len(parts) < 2 or not _PUBLIC_KEY_TYPE.fullmatch(parts[0]):
        raise ValueError("Неподдерживаемый формат публичного SSH-ключа")
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", parts[1]):
        raise ValueError("Повреждённые данные публичного SSH-ключа")
    return key


def create_public_key_install_command(
    ssh_path: str,
    alias: str,
    public_key: str,
    *,
    verify: bool = False,
    identity_file: str | None = None,
) -> PublicKeyInstallCommand:
    normalized_alias = alias.strip()
    if not ssh_path.strip():
        raise ValueError("ssh.exe не найден")
    if not normalized_alias or any(character in normalized_alias for character in "\r\n"):
        raise ValueError("Некорректный SSH-алиас")
    normalized_key = normalize_public_key(public_key)
    script = _VERIFY_SCRIPT if verify else _INSTALL_SCRIPT
    options = ["-T", "-o", "StrictHostKeyChecking=yes"]
    if verify:
        options.extend(["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"])
        if identity_file:
            options.extend(["-o", "IdentitiesOnly=yes", "-i", identity_file])
    return PublicKeyInstallCommand(
        ssh_path,
        tuple([*options, "--", normalized_alias, script]),
        f"{normalized_key}\n".encode("utf-8"),
    )

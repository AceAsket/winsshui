from __future__ import annotations

import os
import sys

from winsshui.credentials import WindowsCredentialStore


def main() -> int:
    prompt = " ".join(sys.argv[1:]).casefold()
    alias = os.environ.get("WINSSHUI_CREDENTIAL_ALIAS", "").strip()
    if not alias or "password" not in prompt:
        return 1
    try:
        credential = WindowsCredentialStore().read(alias)
    except (OSError, ValueError):
        return 1
    if credential is None:
        return 1
    try:
        sys.stdout.write(credential.password + "\n")
        sys.stdout.flush()
    except (AttributeError, OSError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative_path: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / relative_path
    return Path(__file__).resolve().parent / relative_path

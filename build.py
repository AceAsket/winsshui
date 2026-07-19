from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], check=True)


def main() -> int:
    project_root = Path(__file__).resolve().parent
    run("-m", "compileall", "-q", str(project_root / "src"), str(project_root / "tests" / "python"))
    run("-m", "unittest", "discover", "-s", str(project_root / "tests" / "python"), "-v")
    run("-m", "PyInstaller", "--noconfirm", "--clean", str(project_root / "winsshui.spec"))
    print(f"Built: {project_root / 'dist' / 'WinSSH-UI.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


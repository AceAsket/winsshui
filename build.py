from __future__ import annotations

import subprocess
import sys
import os
import shutil
from pathlib import Path


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], check=True)


def main() -> int:
    project_root = Path(__file__).resolve().parent
    run("-m", "compileall", "-q", str(project_root / "src"), str(project_root / "tests" / "python"))
    run("-m", "unittest", "discover", "-s", str(project_root / "tests" / "python"), "-v")
    run("-m", "PyInstaller", "--noconfirm", "--clean", str(project_root / "winsshui.spec"))
    run(
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(project_root / "winsshui-askpass.spec"),
    )
    print(f"Built: {project_root / 'dist' / 'WinSSH-UI.exe'}")
    print(f"Built: {project_root / 'dist' / 'WinSSH-AskPass.exe'}")
    inno_candidates = (
        shutil.which("ISCC.exe"),
        str(Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
    )
    compiler = next((candidate for candidate in inno_candidates if candidate and Path(candidate).is_file()), None)
    if compiler:
        from winsshui import __version__

        subprocess.run(
            [compiler, f"/DMyAppVersion={__version__}", str(project_root / "installer" / "winsshui.iss")],
            check=True,
        )
        print(f"Built: {project_root / 'dist' / 'WinSSH-UI-Setup.exe'}")
    else:
        print("Inno Setup не найден: installer пропущен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

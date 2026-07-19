# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path(SPEC).resolve().parent
icon_path = project_root / "src" / "winsshui" / "assets" / "AppIcon.ico"

a = Analysis(
    [str(project_root / "src" / "winsshui" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[(str(icon_path), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WinSSH-UI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)

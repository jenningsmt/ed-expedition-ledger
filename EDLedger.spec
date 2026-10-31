# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build for ED Expedition Ledger — run build.bat rather than this
# directly (it makes ledger.ico first and then runs Inno Setup).
#
# One onedir bundle, two executables sharing it:
#   EDLedger.exe      windowed: system tray, configuration window
#   EDLedger-cli.exe  console:  --cli, --survey-resolve, --close-leg, ...
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    # Both pick their Windows backend at runtime, invisible to analysis.
    collect_submodules('pystray')
    + collect_submodules('watchdog.observers')
)

a = Analysis(
    ['tracker.pyw'],
    pathex=['.'],
    binaries=[],
    datas=[('engine/rarity_defaults.toml', 'engine')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', '_pytest', 'tests'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

common = dict(
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ledger.ico'],
    version='version_info.txt',
)
exe_gui = EXE(pyz, a.scripts, [], name='EDLedger', console=False, **common)
exe_cli = EXE(pyz, a.scripts, [], name='EDLedger-cli', console=True, **common)

coll = COLLECT(
    exe_gui,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='EDLedger',
)

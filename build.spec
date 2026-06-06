# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------- 1. 收集数据文件 ----------
datas = collect_data_files('anvil')
datas += collect_data_files('flet')
datas += [('translations', 'translations')]

# ---------- 2. 收集隐藏导入 ----------
hiddenimports = []
hiddenimports += collect_submodules('flet')
hiddenimports += collect_submodules('nbtlib')
hiddenimports += collect_submodules('anvil')
hiddenimports += [
    'flet',
    'flet_core',
    'nbtlib',
    'anvil',
    'requests',
    'send2trash',
    'typing_extensions',
    'packaging',
    'packaging.version',
    'packaging.specifiers',
    'packaging.requirements',
]

# ---------- 3. 分析主脚本 ----------
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# ---------- 4. 创建 PYZ 存档 ----------
pyz = PYZ(a.pure)

# ---------- 5. 生成可执行文件（目录模式，更稳定） ----------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MCSaveHelper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='mcsavehelper_icon.ico',
)

# ---------- 6. 收集所有文件到目录 ----------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MCSaveHelper',
)
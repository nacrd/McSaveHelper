# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all, copy_metadata

# ---------- 1. 收集 Flet 全部组件（关键！） ----------
datas_flet, binaries_flet, hidden_flet = collect_all('flet')
datas = list(datas_flet)
binaries = list(binaries_flet)
hiddenimports = list(hidden_flet)

try:
    datas_core, binaries_core, hidden_core = collect_all('flet_core')
    datas += list(datas_core)
    binaries += list(binaries_core)
    hiddenimports += list(hidden_core)
except Exception:
    pass

# Flet 通过 importlib.metadata 定位 Flutter 客户端，必须保留元数据
datas += copy_metadata('flet')
try:
    datas += copy_metadata('flet_core')
except Exception:
    pass

# ---------- 2. 收集其他依赖的数据文件 ----------
datas += collect_data_files('anvil')
datas += collect_data_files('nbtlib')
datas += [('translations', 'translations')]

# ---------- 3. 收集隐藏导入 ----------
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
    'importlib.metadata',
    'importlib.resources',
    'tkinter',
    'tkinter.filedialog',
    '_tkinter',
]

# ---------- 4. 分析主脚本 ----------
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# ---------- 5. 创建 PYZ 存档 ----------
pyz = PYZ(a.pure)

# ---------- 6. 生成单文件可执行文件 ----------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MCSaveHelper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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

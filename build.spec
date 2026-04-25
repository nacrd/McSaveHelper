# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files

# ---------- 1. 收集 anvil 包中的所有数据文件（.json等） ----------
datas = collect_data_files('anvil')
# 打包翻译文件
datas += [('translations', 'translations')]

# ---------- 2. 分析主脚本 ----------
a = Analysis(
    ['main.py'],
    pathex=[],                     # 可添加额外搜索路径，如 ['E:\\coding\\mcsavehelper']
    binaries=[],                   # 留空，让 PyInstaller 自动处理 DLL
    datas=datas,                   # 包含 anvil 的数据文件
    hiddenimports=[                # 显式导入可能被遗漏的模块
        'flet',
        'nbtlib',
        'requests',
        'send2trash',
        # 如果你的代码中还 import 了其他第三方库，请在此添加
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['typing_extensions'],
    noarchive=False,
    optimize=0,
)

# ---------- 3. 创建 PYZ 存档 ----------
pyz = PYZ(a.pure)

# ---------- 4. 生成单文件可执行文件 ----------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MCSaveHelper',            # 输出的 exe 文件名
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                      # 是否使用 UPX 压缩（需安装 upx 并加入 PATH）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                  # 显示控制台窗口（调试用，发布时可改为 False）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,                  # 单文件模式
    icon='mcsavehelper_icon.ico',   # 应用程序图标文件路径
)
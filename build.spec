# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files

# 获取 spec 文件所在目录
spec_root = os.path.dirname(os.path.abspath(SPECPATH))
icon_path = os.path.join(spec_root, 'assets', 'icon.ico')

# 检查图标是否存在
if not os.path.isfile(icon_path):
    icon_path = None  # 不存在则不用图标

datas = collect_data_files('anvil_parser2')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['customtkinter', 'nbtlib', 'anvil_parser2', 'requests', 'send2trash'],
    # ... 其余保持不变
)

pyz = PYZ(a.pure)

exe_kwargs = {
    'pyz': pyz,
    'scripts': a.scripts,
    'binaries': a.binaries,
    'datas': a.datas,
    'name': 'MC-Migrator-Pro',
    'debug': False,
    'bootloader_ignore_signals': False,
    'strip': False,
    'upx': True,
    'upx_exclude': [],
    'runtime_tmpdir': None,
    'console': False,
    'disable_windowed_traceback': False,
    'argv_emulation': False,
    'target_arch': None,
    'codesign_identity': None,
    'entitlements_file': None,
}

if icon_path:
    exe_kwargs['icon'] = icon_path

exe = EXE(**exe_kwargs)

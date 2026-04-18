import sys
import os
from PyInstaller.utils.hooks import collect_data_files

# 获取 spec 文件所在目录
spec_root = os.path.dirname(os.path.abspath(SPECPATH))
icon_path = os.path.join(spec_root, 'assets', 'icon.ico')
if not os.path.isfile(icon_path):
    icon_path = None

datas = collect_data_files('anvil_parser2')

# ===== 添加 Python DLL =====
python_version = f'python{sys.version_info.major}{sys.version_info.minor}'
python_dll = os.path.join(os.path.dirname(sys.executable), f'{python_version}.dll')
binaries = []
if os.path.isfile(python_dll):
    binaries.append((python_dll, '.'))  # 拷贝到 exe 同级目录

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=['customtkinter', 'nbtlib', 'anvil_parser2', 'requests', 'send2trash'],
)

pyz = PYZ(a.pure)

exe_kwargs = {
    'pyz': pyz,
    'scripts': a.scripts,
    'binaries': a.binaries,
    'datas': a.datas,
    'name': 'MC-Migrator',
    'debug': False,
    'bootloader_ignore_signals': False,
    'strip': False,
    'upx': True,
    'upx_exclude': [],
    'runtime_tmpdir': None,
    'console': False,
}

if icon_path:
    exe_kwargs['icon'] = icon_path

exe = EXE(**exe_kwargs)
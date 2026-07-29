"""启动时一次性数据迁移：统一应用主目录名称。"""
from __future__ import annotations

from pathlib import Path

_LEGACY_HOME_DIR = ".mcsavehelper"
_CURRENT_HOME_DIR = ".mc_save_helper"


def migrate_legacy_home_dir() -> None:
    """将 ``~/.mcsavehelper`` 重命名为 ``~/.mc_save_helper``（仅一次）。

    如果旧目录不存在或新目录已存在则静默返回。
    """
    old = Path.home() / _LEGACY_HOME_DIR
    new = Path.home() / _CURRENT_HOME_DIR
    if not old.is_dir() or new.exists():
        return
    try:
        old.rename(new)
    except OSError:
        pass

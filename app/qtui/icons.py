"""Qt 图标系统：Unicode 字形映射，替代 Flet 的 Material 图标。"""
from __future__ import annotations

from typing import Final

# 侧边栏导航字形使用单色 Unicode 符号，避免系统 Emoji 字体造成彩色视觉噪声。
NAV_GLYPHS: Final[dict[str, str]] = {
    "WORLD_INFO": "▦",
    "PLAYER": "♙",
    "MAP": "⌖",
    "STATS": "▥",
    "SEARCH": "⌕",
    "NBT": "{}",
    "PACKAGE": "▣",
    "BUILD": "◇",
    "BALANCE": "≋",
    "LINK": "↗",
    "CLIPBOARD": "≡",
    "SETTINGS": "⚙",
}

# 通用动作字形
ACTION_GLYPHS: Final[dict[str, str]] = {
    "EXPLORE": "⌁",
    "HISTORY": "◷",
    "CLEANUP": "⌫",
    "VERIFY": "✓",
    "RESTORE": "↺",
    "FOLDER": "□",
    "FOLDER_OPEN": "⌑",
    "SAVE": "▣",
    "REFRESH": "↻",
    "SEARCH": "⌕",
    "COPY": "⧉",
    "DELETE": "×",
    "ERROR": "!",
    "WARNING": "!",
    "INFO": "i",
    "SUCCESS": "✓",
    "BACK": "←",
    "CLOSE": "×",
    "EXPAND": "›",
    "COLLAPSE": "‹",
    "PLUS": "+",
    "PICKAXE": "⛏",
    "CLOCK": "◷",
    "CHEVRON_RIGHT": "›",
    "CHEVRON_DOWN": "⌄",
    "ARROW_RIGHT": "→",
    "ARROW_LEFT": "←",
}


def glyph(name: str) -> str:
    """返回命名图标的字形；未知名称返回占位符。"""
    return NAV_GLYPHS.get(name) or ACTION_GLYPHS.get(name, "•")

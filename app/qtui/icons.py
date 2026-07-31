"""Qt 图标系统：Unicode 字形映射，替代 Flet 的 Material 图标。"""
from __future__ import annotations

from typing import Final

# 侧边栏导航字形（key 与 Flet 版 IconSet 成员名一致，便于对照迁移）
NAV_GLYPHS: Final[dict[str, str]] = {
    "MAP": "🗺️",
    "PACKAGE": "📦",
    "BUILD": "🧱",
    "BALANCE": "⚖️",
    "LINK": "🔗",
    "CLIPBOARD": "📄",
    "SETTINGS": "⚙️",
}

# 通用动作字形
ACTION_GLYPHS: Final[dict[str, str]] = {
    "EXPLORE": "🧭",
    "FOLDER": "📁",
    "FOLDER_OPEN": "📂",
    "SAVE": "💾",
    "REFRESH": "🔄",
    "SEARCH": "🔍",
    "COPY": "📋",
    "DELETE": "🗑️",
    "ERROR": "⛔",
    "WARNING": "⚠️",
    "INFO": "ℹ️",
    "SUCCESS": "✅",
    "BACK": "⬅️",
    "CLOSE": "✖️",
    "EXPAND": "▶️",
    "COLLAPSE": "◀️",
    "PLUS": "➕",
}


def glyph(name: str) -> str:
    """返回命名图标的字形；未知名称返回占位符。"""
    return NAV_GLYPHS.get(name) or ACTION_GLYPHS.get(name, "•")

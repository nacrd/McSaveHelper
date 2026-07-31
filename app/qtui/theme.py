"""Qt 主题系统：色板 + QSS 生成 + 运行时切换。

色板值与 Flet 版 ``app/ui/theme.py`` 的 ``DARK_THEME``/``LIGHT_THEME`` 一致
（过渡期复制，Flet 树删除后本文件成为唯一权威）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class QtThemeColors:
    """Minecraft 风格色板（与 Flet 版 ThemeColors 对齐）。"""

    mode: str
    bg_primary: str
    bg_secondary: str
    bg_card: str
    bg_card_hover: str
    bg_elevated: str
    border_light: str
    border_dark: str
    border_standard: str
    border_subtle: str
    border_glow: str
    accent: str
    accent_hover: str
    accent_dim: str
    success: str
    warning: str
    error: str
    info: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_disabled: str
    text_invert: str
    terminal_green: str
    terminal_yellow: str
    terminal_red: str
    terminal_blue: str
    terminal_cyan: str
    terminal_purple: str
    log_bg: str
    log_border: str


DARK_THEME = QtThemeColors(
    mode="dark",
    bg_primary="#111513",
    bg_secondary="#171C19",
    bg_card="#1D231F",
    bg_card_hover="#252D28",
    bg_elevated="#29312C",
    border_light="#3B463F",
    border_dark="#090C0A",
    border_standard="#647269",
    border_subtle="#3D4A42",
    border_glow="#63D5E5",
    accent="#63C174",
    accent_hover="#78D28A",
    accent_dim="#438A52",
    success="#3FBF8A",
    warning="#E5B454",
    error="#E06C75",
    info="#63D5E5",
    text_primary="#F2F5F3",
    text_secondary="#C3CBC6",
    text_muted="#AAB7AF",
    text_disabled="#718078",
    text_invert="#0E1510",
    terminal_green="#78D28A",
    terminal_yellow="#E5B454",
    terminal_red="#E06C75",
    terminal_blue="#72A7E5",
    terminal_cyan="#63D5E5",
    terminal_purple="#B19CD9",
    log_bg="#0D110F",
    log_border="#28312B",
)

LIGHT_THEME = QtThemeColors(
    mode="light",
    bg_primary="#F3F6F4",
    bg_secondary="#E9EEEB",
    bg_card="#FFFFFF",
    bg_card_hover="#F0F5F1",
    bg_elevated="#FFFFFF",
    border_light="#D8E0DB",
    border_dark="#AEB9B2",
    border_standard="#7D8C82",
    border_subtle="#A8B5AD",
    border_glow="#168FA3",
    accent="#347A45",
    accent_hover="#408F53",
    accent_dim="#2C663A",
    success="#147A5B",
    warning="#8A5A08",
    error="#B64049",
    info="#0B7182",
    text_primary="#172019",
    text_secondary="#425047",
    text_muted="#4E5E54",
    text_disabled="#7A867F",
    text_invert="#FFFFFF",
    terminal_green="#2A8A2A",
    terminal_yellow="#B07800",
    terminal_red="#CC3333",
    terminal_blue="#3366AA",
    terminal_cyan="#228888",
    terminal_purple="#7744AA",
    log_bg="#172019",
    log_border="#7D8C82",
)


_THEMES: dict[str, QtThemeColors] = {"dark": DARK_THEME, "light": LIGHT_THEME}


def build_qss(colors: QtThemeColors) -> str:
    """根据色板生成应用级 QSS 样式表。"""
    return f"""
QWidget {{
    background-color: {colors.bg_primary};
    color: {colors.text_primary};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {colors.bg_primary};
}}
QLabel {{
    background: transparent;
}}
QLabel[role="muted"] {{
    color: {colors.text_muted};
}}
QLabel[role="title"] {{
    font-size: 20px;
    font-weight: 600;
}}
QLabel[role="section"] {{
    font-size: 15px;
    font-weight: 600;
    color: {colors.text_secondary};
}}
QFrame[role="card"] {{
    background-color: {colors.bg_card};
    border: 1px solid {colors.border_subtle};
    border-radius: 6px;
}}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {colors.bg_elevated};
    border: 1px solid {colors.border_standard};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {colors.accent};
    selection-color: {colors.text_invert};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus {{
    border: 2px solid {colors.border_glow};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled,
QCheckBox:disabled, QPushButton:disabled {{
    color: {colors.text_disabled};
    background-color: {colors.bg_secondary};
    border-color: {colors.border_subtle};
}}
QComboBox QAbstractItemView {{
    background-color: {colors.bg_elevated};
    border: 1px solid {colors.border_standard};
    selection-background-color: {colors.accent};
    selection-color: {colors.text_invert};
}}
QPushButton {{
    background-color: {colors.bg_card};
    border: 1px solid {colors.border_standard};
    border-radius: 4px;
    padding: 6px 14px;
    color: {colors.text_primary};
}}
QPushButton:hover {{
    background-color: {colors.bg_card_hover};
    border-color: {colors.border_light};
}}
QPushButton:pressed {{
    background-color: {colors.bg_elevated};
}}
QPushButton:disabled {{
    color: {colors.text_disabled};
    background-color: {colors.bg_secondary};
    border-color: {colors.border_subtle};
}}
QPushButton[role="primary"] {{
    background-color: {colors.accent};
    border-color: {colors.accent_dim};
    color: {colors.text_invert};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background-color: {colors.accent_hover};
}}
QPushButton[role="danger"] {{
    background-color: {colors.error};
    border-color: {colors.border_dark};
    color: {colors.text_invert};
}}
QPushButton[role="ghost"] {{
    background-color: transparent;
    border: 1px solid {colors.border_standard};
}}
QPushButton[role="ghost"]:hover {{
    background-color: {colors.bg_card_hover};
}}
QCheckBox {{
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
}}
QCheckBox::indicator:unchecked {{
    border: 1px solid {colors.border_standard};
    background: {colors.bg_elevated};
    border-radius: 3px;
}}
QCheckBox::indicator:checked {{
    border: 1px solid {colors.accent_dim};
    background: {colors.accent};
    border-radius: 3px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {colors.bg_secondary};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {colors.border_standard};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {colors.bg_secondary};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {colors.border_standard};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QProgressBar {{
    border: 1px solid {colors.border_standard};
    border-radius: 4px;
    background: {colors.bg_secondary};
    text-align: center;
    color: {colors.text_primary};
}}
QProgressBar::chunk {{
    background-color: {colors.accent};
    border-radius: 3px;
}}
QStatusBar {{
    background: {colors.bg_secondary};
    border-top: 1px solid {colors.border_subtle};
    color: {colors.text_secondary};
}}
QToolTip {{
    background-color: {colors.bg_elevated};
    color: {colors.text_primary};
    border: 1px solid {colors.border_standard};
}}
QListWidget, QTreeWidget {{
    background: {colors.bg_secondary};
    border: 1px solid {colors.border_subtle};
    border-radius: 4px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {colors.accent_dim};
    color: {colors.text_primary};
}}
QTableWidget {{
    background: {colors.bg_secondary};
    border: 1px solid {colors.border_subtle};
    gridline-color: {colors.border_subtle};
}}
QHeaderView::section {{
    background: {colors.bg_elevated};
    color: {colors.text_secondary};
    border: none;
    border-right: 1px solid {colors.border_subtle};
    padding: 4px 8px;
}}
QMenuBar {{
    background: {colors.bg_secondary};
    color: {colors.text_primary};
}}
QMenu {{
    background: {colors.bg_elevated};
    border: 1px solid {colors.border_standard};
}}
QMenu::item:selected {{
    background: {colors.accent_dim};
}}
QMessageBox {{
    background: {colors.bg_card};
}}
"""


def apply_theme(app: QApplication, mode: str) -> QtThemeColors:
    """应用主题并返回当前色板。

    Args:
        app: QApplication 实例。
        mode: ``dark`` 或 ``light``。

    Raises:
        ValueError: 未知主题模式。
    """
    colors = _THEMES.get(mode.lower())
    if colors is None:
        raise ValueError(f"未知主题模式: {mode}，可用: {list(_THEMES)}")
    app.setStyleSheet(build_qss(colors))
    _apply_palette(app, colors)
    return colors


def _apply_palette(app: QApplication, colors: QtThemeColors) -> None:
    """同步 QPalette，保证原生对话框等控件跟随主题。"""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors.bg_primary))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors.text_primary))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors.bg_card))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors.bg_secondary))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors.text_primary))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors.bg_card))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors.text_primary))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors.text_invert))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors.bg_elevated))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors.text_primary))
    app.setPalette(palette)


class QtThemeManager:
    """运行时主题切换单例（进程级基础设施，允许共享生命周期）。"""

    _instance: Optional["QtThemeManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "QtThemeManager":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._initialized = False
            cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._mode: str = "dark"
        self._current: QtThemeColors = DARK_THEME
        self._listeners: list[Callable[[str], None]] = []
        self._initialized = True

    @property
    def current(self) -> QtThemeColors:
        """返回当前主题色板。"""
        return self._current

    @property
    def mode(self) -> str:
        """返回当前主题模式名。"""
        return self._mode

    def set_mode(self, mode: str) -> None:
        """切换主题模式。

        Args:
            mode: ``dark`` 或 ``light``。

        Raises:
            ValueError: 未知主题模式。
        """
        normalized = mode.lower()
        colors = _THEMES.get(normalized)
        if colors is None:
            raise ValueError(f"未知主题模式: {mode}，可用: {list(_THEMES)}")
        if normalized == self._mode:
            return
        self._mode = normalized
        self._current = colors
        for callback in list(self._listeners):
            try:
                callback(normalized)
            except Exception:
                # best-effort：主题监听器失败不应中断切换。
                pass

    def toggle(self) -> str:
        """切换主题模式。

        Returns:
            切换后的主题模式名。
        """
        new_mode = "light" if self._mode == "dark" else "dark"
        self.set_mode(new_mode)
        return new_mode

    def register_listener(self, callback: Callable[[str], None]) -> None:
        """注册主题切换监听器。"""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[str], None]) -> None:
        """注销主题切换监听器。"""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass


def get_theme_manager() -> QtThemeManager:
    """返回主题管理器单例。"""
    return QtThemeManager()

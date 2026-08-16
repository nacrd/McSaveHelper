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

    # Minecraft 方块色
    mc_stone: str
    mc_dirt: str
    mc_grass: str
    mc_wood: str
    mc_diamond: str
    mc_gold: str
    mc_iron: str
    mc_coal: str
    mc_emerald: str
    mc_redstone: str
    mc_obsidian: str
    mc_nether: str
    mc_end: str

    log_bg: str
    log_border: str


DARK_THEME = QtThemeColors(
    mode="dark",
    bg_primary="#11161A",
    bg_secondary="#171E24",
    bg_card="#1D262D",
    bg_card_hover="#26323A",
    bg_elevated="#2A3740",
    border_light="#53636C",
    border_dark="#0A0E11",
    border_standard="#43535C",
    border_subtle="#2D3A42",
    border_glow="#5FE0D0",
    accent="#57C7B5",
    accent_hover="#73D8C8",
    accent_dim="#2F8D83",
    success="#67D391",
    warning="#F4C36A",
    error="#F07D7D",
    info="#65B9F6",
    text_primary="#F3F7F8",
    text_secondary="#C5D1D5",
    text_muted="#91A1A9",
    text_disabled="#64737B",
    text_invert="#0B1215",
    terminal_green="#73D8C8",
    terminal_yellow="#F4C36A",
    terminal_red="#F07D7D",
    terminal_blue="#65B9F6",
    terminal_cyan="#5FE0D0",
    terminal_purple="#C3A8E8",
    mc_stone="#66747B",
    mc_dirt="#80634E",
    mc_grass="#57C7B5",
    mc_wood="#252F35",
    mc_diamond="#5FE0D0",
    mc_gold="#F4C36A",
    mc_iron="#B5C0C4",
    mc_coal="#171E24",
    mc_emerald="#67D391",
    mc_redstone="#F07D7D",
    mc_obsidian="#0B1013",
    mc_nether="#A85B66",
    mc_end="#8C78B2",
    log_bg="#0C1115",
    log_border="#243139",
)

LIGHT_THEME = QtThemeColors(
    mode="light",
    bg_primary="#F4F7F8",
    bg_secondary="#EAF0F2",
    bg_card="#FFFFFF",
    bg_card_hover="#F0F7F6",
    bg_elevated="#FFFFFF",
    border_light="#D8E2E5",
    border_dark="#AAB9BE",
    border_standard="#B8C8CD",
    border_subtle="#D3DEE1",
    border_glow="#178B7C",
    accent="#178B7C",
    accent_hover="#249F90",
    accent_dim="#BDE7E1",
    success="#197A52",
    warning="#A36909",
    error="#C94F5B",
    info="#176EA7",
    text_primary="#172126",
    text_secondary="#43535A",
    text_muted="#64767D",
    text_disabled="#97A5AA",
    text_invert="#FFFFFF",
    terminal_green="#197A52",
    terminal_yellow="#A36909",
    terminal_red="#C94F5B",
    terminal_blue="#176EA7",
    terminal_cyan="#178B7C",
    terminal_purple="#7653A6",
    mc_stone="#74858B",
    mc_dirt="#86674F",
    mc_grass="#178B7C",
    mc_wood="#EAF0F2",
    mc_diamond="#178B7C",
    mc_gold="#A36909",
    mc_iron="#74858B",
    mc_coal="#D8E2E5",
    mc_emerald="#197A52",
    mc_redstone="#C94F5B",
    mc_obsidian="#172126",
    mc_nether="#98505A",
    mc_end="#765C9A",
    log_bg="#172126",
    log_border="#B8C8CD",
)


_THEMES: dict[str, QtThemeColors] = {"dark": DARK_THEME, "light": LIGHT_THEME}


def build_qss(colors: QtThemeColors) -> str:
    """根据色板生成应用级 QSS 样式表。"""
    return f"""
QWidget {{
    background-color: {colors.bg_primary};
    color: {colors.text_primary};
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background-color: {colors.bg_primary};
}}
QWidget#top_bar {{
    background-color: {colors.bg_secondary};
    border-bottom: 1px solid {colors.border_subtle};
}}
QFrame#world_context_bar {{
    background-color: {colors.bg_secondary};
    border: none;
}}
QLabel#world_context_icon {{
    background-color: {colors.bg_elevated};
    color: {colors.accent};
    border: 1px solid {colors.border_standard};
    border-radius: 8px;
    font-size: 16px;
}}
QLabel#world_context_name {{
    color: {colors.text_primary};
    font-size: 14px;
    font-weight: 600;
}}
QLabel[contextStatus="required"] {{
    color: {colors.warning};
    border: 1px solid {colors.warning};
    border-radius: 7px;
    padding: 2px 7px;
}}
QLabel[contextStatus="loading"] {{
    color: {colors.info};
    border: 1px solid {colors.info};
    border-radius: 7px;
    padding: 2px 7px;
}}
QLabel[contextStatus="ready"] {{
    color: {colors.success};
    border: 1px solid {colors.success};
    border-radius: 7px;
    padding: 2px 7px;
}}
QLabel[contextStatus="error"] {{
    color: {colors.error};
    border: 1px solid {colors.error};
    border-radius: 7px;
    padding: 2px 7px;
}}
QLabel[role="navigationGroup"] {{
    color: {colors.text_muted};
    font-size: 10px;
    font-weight: 600;
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
    color: {colors.text_primary};
    padding-left: 8px;
    border-left: 3px solid {colors.accent};
}}
QLabel[role="warning"] {{
    color: {colors.warning};
}}
QLabel[role="error"] {{
    color: {colors.error};
}}
QLabel[role="info"] {{
    color: {colors.info};
}}
QLabel[role="success"] {{
    color: {colors.success};
}}
QLabel[role="result"] {{
    color: {colors.text_primary};
    font-family: 'Consolas', 'SFMono-Regular', monospace;
}}
QFrame[role="card"] {{
    background-color: {colors.bg_card};
    border: 1px solid {colors.border_subtle};
    border-radius: 8px;
}}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {colors.bg_elevated};
    border: 1px solid {colors.border_standard};
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: {colors.accent};
    selection-color: {colors.text_invert};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus {{
    border: 1px solid {colors.border_glow};
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
QTabWidget::pane {{
    border: 1px solid {colors.border_subtle};
    border-radius: 8px;
    background: {colors.bg_secondary};
}}
QTabBar::tab {{
    background: transparent;
    color: {colors.text_secondary};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 8px 16px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{
    background: {colors.bg_card};
    color: {colors.text_primary};
}}
QTabBar::tab:selected {{
    background: {colors.bg_elevated};
    color: {colors.text_primary};
    border-color: {colors.border_standard};
    font-weight: 600;
}}
QTabBar::tab:disabled {{
    color: {colors.text_disabled};
}}
QPushButton {{
    background-color: {colors.bg_card};
    border: 1px solid {colors.border_standard};
    border-radius: 6px;
    padding: 8px 14px;
    color: {colors.text_primary};
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: {colors.bg_card_hover};
    border-color: {colors.border_light};
}}
QPushButton:pressed {{
    background-color: {colors.bg_elevated};
    border-color: {colors.accent_dim};
}}
QPushButton:checked {{
    background-color: {colors.accent_dim};
    border-color: {colors.accent};
    color: {colors.text_primary};
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
    border-color: {colors.accent};
}}
QPushButton[role="primary"]:pressed {{
    background-color: {colors.accent_dim};
}}
QPushButton[role="danger"] {{
    background-color: {colors.error};
    border-color: {colors.border_dark};
    color: {colors.text_invert};
}}
QPushButton[role="danger"]:hover {{
    background-color: #BF5260;
}}
QPushButton[role="ghost"] {{
    background-color: transparent;
    border: 1px solid {colors.border_standard};
}}
QPushButton[role="ghost"]:hover {{
    background-color: {colors.bg_card_hover};
}}
QPushButton[role="ghost"]:checked {{
    background-color: {colors.bg_card};
    border-color: {colors.accent};
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid {colors.border_standard};
    border-radius: 6px;
    padding: 7px 10px;
    color: {colors.text_secondary};
}}
QToolButton:hover {{
    background-color: {colors.bg_card_hover};
    color: {colors.text_primary};
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
    width: 9px;
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
    height: 9px;
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
    border-radius: 5px;
    background: {colors.bg_secondary};
    text-align: center;
    color: {colors.text_primary};
    min-height: 14px;
}}
QProgressBar::chunk {{
    background-color: {colors.accent};
    border-radius: 4px;
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
    border-radius: 5px;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 3px 6px;
    border-radius: 4px;
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background: {colors.bg_card};
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {colors.accent_dim};
    color: {colors.text_primary};
}}
QTableWidget {{
    background: {colors.bg_secondary};
    border: 1px solid {colors.border_subtle};
    border-radius: 7px;
    gridline-color: {colors.border_subtle};
    selection-background-color: {colors.accent_dim};
    selection-color: {colors.text_primary};
}}
QTableWidget::item:hover {{
    background: {colors.bg_card};
}}
QHeaderView::section {{
    background: {colors.bg_elevated};
    color: {colors.text_secondary};
    border: none;
    border-bottom: 1px solid {colors.border_subtle};
    border-right: 1px solid {colors.border_subtle};
    padding: 7px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: {colors.bg_elevated};
    border: none;
}}
QGroupBox {{
    border: 1px solid {colors.border_subtle};
    border-radius: 6px;
    margin-top: 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {colors.text_secondary};
}}
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:hover {{
    background: {colors.border_subtle};
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

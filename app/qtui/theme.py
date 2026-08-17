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
    bg_primary="#101416",
    bg_secondary="#151B1E",
    bg_card="#1B2327",
    bg_card_hover="#222D31",
    bg_elevated="#273338",
    border_light="#506067",
    border_dark="#090D0F",
    border_standard="#3B4A50",
    border_subtle="#29353A",
    border_glow="#39C2AE",
    accent="#2FB7A3",
    accent_hover="#47C8B5",
    accent_dim="#183F3B",
    success="#57C987",
    warning="#E5B85F",
    error="#E66D78",
    info="#5AADE3",
    text_primary="#F3F6F7",
    text_secondary="#C1CDD1",
    text_muted="#87979D",
    text_disabled="#5C6B70",
    text_invert="#08110F",
    terminal_green="#57C987",
    terminal_yellow="#E5B85F",
    terminal_red="#E66D78",
    terminal_blue="#5AADE3",
    terminal_cyan="#39C2AE",
    terminal_purple="#B29AD8",
    mc_stone="#64747A",
    mc_dirt="#80634E",
    mc_grass="#2FB7A3",
    mc_wood="#252F33",
    mc_diamond="#39C2AE",
    mc_gold="#E5B85F",
    mc_iron="#B5C0C4",
    mc_coal="#151B1E",
    mc_emerald="#57C987",
    mc_redstone="#E66D78",
    mc_obsidian="#090D0F",
    mc_nether="#A85B66",
    mc_end="#8874AA",
    log_bg="#0B0F11",
    log_border="#222E33",
)

LIGHT_THEME = QtThemeColors(
    mode="light",
    bg_primary="#F4F6F7",
    bg_secondary="#FFFFFF",
    bg_card="#FFFFFF",
    bg_card_hover="#EDF3F2",
    bg_elevated="#F1F5F5",
    border_light="#D5DEE1",
    border_dark="#A6B3B8",
    border_standard="#C1CDD1",
    border_subtle="#DCE3E5",
    border_glow="#0E897A",
    accent="#0E897A",
    accent_hover="#087668",
    accent_dim="#D8EFEB",
    success="#237A50",
    warning="#A96D0B",
    error="#CB4F5D",
    info="#287EAA",
    text_primary="#182226",
    text_secondary="#46565C",
    text_muted="#6B7A80",
    text_disabled="#9AA7AC",
    text_invert="#FFFFFF",
    terminal_green="#237A50",
    terminal_yellow="#A96D0B",
    terminal_red="#CB4F5D",
    terminal_blue="#287EAA",
    terminal_cyan="#0E897A",
    terminal_purple="#7653A6",
    mc_stone="#74858B",
    mc_dirt="#86674F",
    mc_grass="#0E897A",
    mc_wood="#EDF1F2",
    mc_diamond="#0E897A",
    mc_gold="#A96D0B",
    mc_iron="#74858B",
    mc_coal="#D8E2E5",
    mc_emerald="#237A50",
    mc_redstone="#CB4F5D",
    mc_obsidian="#172126",
    mc_nether="#98505A",
    mc_end="#765C9A",
    log_bg="#172126",
    log_border="#C1CDD1",
)


_THEMES: dict[str, QtThemeColors] = {"dark": DARK_THEME, "light": LIGHT_THEME}


def build_qss(colors: QtThemeColors) -> str:
    """根据色板生成应用级 QSS 样式表。"""
    return f"""
QWidget {{
    background-color: transparent;
    color: {colors.text_primary};
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 10pt;
}}
QMainWindow, QDialog {{
    background-color: {colors.bg_primary};
}}
QWidget#top_bar {{
    background-color: {colors.bg_secondary};
    border-bottom: 1px solid {colors.border_subtle};
}}
QWidget#page_header {{
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
QLabel[role="caption"], QLabel[size="caption"] {{
    color: {colors.text_muted};
    font-size: 9pt;
}}
QLabel[role="title"] {{
    font-size: 20px;
    font-weight: 600;
}}
QLabel[role="pageIcon"] {{
    background-color: {colors.bg_elevated};
    color: {colors.accent};
    border: 1px solid {colors.border_standard};
    border-radius: 6px;
    font-size: 19px;
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
QWidget[role="state"] {{
    background-color: {colors.bg_card};
    border: 1px solid {colors.border_subtle};
    border-radius: 7px;
}}
QLabel[role="stateIcon"] {{
    color: {colors.text_muted};
    font-size: 36px;
}}
QLabel[role="stateTitle"] {{
    color: {colors.text_primary};
    font-size: 16px;
    font-weight: 600;
}}
QLabel[role="stateSubtitle"] {{
    color: {colors.text_muted};
    font-size: 10pt;
}}
QProgressBar[role="stateLoading"] {{
    border: none;
    border-radius: 3px;
    background: {colors.bg_elevated};
}}
QProgressBar[role="stateLoading"]::chunk {{
    background: {colors.accent};
    border-radius: 3px;
}}
QLabel[role="cardTitle"] {{
    color: {colors.text_primary};
    font-size: 10pt;
    font-weight: 600;
}}
QLabel[role="statusIcon"] {{
    font-size: 15pt;
}}
QLabel[role="statusIcon"][tone="success"] {{
    color: {colors.success};
}}
QLabel[role="statusIcon"][tone="error"] {{
    color: {colors.error};
}}
QLabel[role="statusChip"] {{
    border: 1px solid {colors.border_subtle};
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 9pt;
    font-weight: 600;
}}
QLabel[role="statusChip"][feedbackStatus="neutral"] {{
    background-color: {colors.bg_elevated};
    color: {colors.text_muted};
}}
QLabel[role="statusChip"][feedbackStatus="pending"] {{
    background-color: {colors.bg_elevated};
    border-color: {colors.warning};
    color: {colors.warning};
}}
QLabel[role="statusChip"][feedbackStatus="saved"] {{
    background-color: {colors.accent_dim};
    border-color: {colors.success};
    color: {colors.success};
}}
QLabel[role="statusChip"][feedbackStatus="failed"] {{
    background-color: {colors.bg_elevated};
    border-color: {colors.error};
    color: {colors.error};
}}
QLabel[role="result"] {{
    color: {colors.text_primary};
    font-family: 'Consolas', 'SFMono-Regular', monospace;
}}
QWidget[role="card"] {{
    background-color: {colors.bg_card};
    border: 1px solid {colors.border_subtle};
    border-radius: 7px;
}}
QWidget[role="interactiveCard"] {{
    background-color: {colors.bg_card};
    border: 1px solid {colors.border_subtle};
    border-radius: 7px;
}}
QWidget[role="interactiveCard"]:hover {{
    background-color: {colors.bg_card_hover};
    border-color: {colors.border_standard};
}}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {colors.bg_elevated};
    border: 1px solid {colors.border_standard};
    border-radius: 6px;
    padding: 6px 10px;
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
    padding: 6px 12px;
    color: {colors.text_primary};
    min-height: 20px;
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
QPushButton:focus, QToolButton:focus {{
    border: 1px solid {colors.border_glow};
}}
QPushButton[role="danger"]:hover {{
    background-color: #BF5260;
}}
QPushButton[role="warning"] {{
    background-color: {colors.warning};
    border-color: {colors.warning};
    color: {colors.text_invert};
    font-weight: 600;
}}
QPushButton[role="warning"]:hover {{
    background-color: {colors.accent_hover};
    border-color: {colors.accent_hover};
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
QPushButton[role="sectionToggle"] {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    color: {colors.text_primary};
    padding: 10px 14px;
    text-align: left;
    font-weight: 600;
}}
QPushButton[role="sectionToggle"]:hover {{
    background-color: {colors.bg_card_hover};
}}
QPushButton[role="sectionToggle"][expanded="true"] {{
    color: {colors.accent};
}}
QPushButton[role="icon"] {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
}}
QPushButton[role="icon"]:hover {{
    background-color: {colors.bg_elevated};
    border-color: {colors.border_standard};
}}
QPushButton[role="icon"][tone="danger"] {{
    color: {colors.error};
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid {colors.border_standard};
    border-radius: 6px;
    padding: 6px 10px;
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
    background: transparent;
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background: {colors.border_light};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {colors.border_light};
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
    padding: 2px 8px;
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
    alternate-background-color: {colors.bg_card};
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
    padding: 6px 8px;
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

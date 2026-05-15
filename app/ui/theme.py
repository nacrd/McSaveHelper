"""深色主题色彩定义（来自 Linear 设计系统）"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeColors:
    bg_primary: str = "#0f1011"
    bg_secondary: str = "#08090a"
    bg_card: str = "#191a1b"
    bg_card_hover: str = "#28282c"
    border: str = "#23252a"
    border_secondary: str = "#34343a"
    border_tertiary: str = "#3e3e44"
    border_subtle: str = "rgba(255,255,255,0.05)"
    border_standard: str = "rgba(255,255,255,0.08)"

    accent: str = "#5e6ad2"
    accent_hover: str = "#7170ff"
    accent_light: str = "#828fff"

    success: str = "#27a644"
    success_light: str = "#10b981"
    warning: str = "#D29922"
    warning_light: str = "#E3B341"
    error: str = "#F85149"
    error_light: str = "#F78166"

    text_primary: str = "#f7f8f8"
    text_secondary: str = "#d0d6e0"
    text_muted: str = "#8a8f98"
    text_quaternary: str = "#62666d"

    log_bg: str = "#08090a"
    log_border: str = "#23252a"

    terminal_green: str = "#7EE787"
    terminal_yellow: str = "#E3B341"
    terminal_red: str = "#F47067"
    terminal_blue: str = "#79C0FF"
    terminal_purple: str = "#D2A8FF"
    terminal_cyan: str = "#79C0FF"

    shadow: str = "rgba(0, 0, 0, 0.3)"
    gradient_start: str = "#191a1b"
    gradient_end: str = "#0f1011"


# 单例主题实例
THEME = ThemeColors()

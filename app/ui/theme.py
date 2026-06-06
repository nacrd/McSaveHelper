"""Minecraft 风格主题色彩定义"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeColors:
    bg_primary: str = "#2C2C2C"
    bg_secondary: str = "#1E1E1E"
    bg_card: str = "#373737"
    bg_card_hover: str = "#454545"
    border: str = "#555555"
    border_secondary: str = "#6B6B6B"
    border_tertiary: str = "#8E8E8E"
    border_subtle: str = "#4A4A4A"
    border_standard: str = "#5A5A5A"

    accent: str = "#55FF55"
    accent_hover: str = "#7AFF7A"
    accent_light: str = "#88FF88"

    success: str = "#55FF55"
    success_light: str = "#7AFF7A"
    warning: str = "#FFAA00"
    warning_light: str = "#FFCC44"
    error: str = "#FF5555"
    error_light: str = "#FF7777"

    text_primary: str = "#FFFFFF"
    text_secondary: str = "#CCCCCC"
    text_muted: str = "#888888"
    text_quaternary: str = "#666666"

    log_bg: str = "#1A1A1A"
    log_border: str = "#4A4A4A"

    terminal_green: str = "#55FF55"
    terminal_yellow: str = "#FFAA00"
    terminal_red: str = "#FF5555"
    terminal_blue: str = "#5555FF"
    terminal_purple: str = "#AA55FF"
    terminal_cyan: str = "#55FFFF"

    shadow: str = "rgba(0, 0, 0, 0.5)"
    gradient_start: str = "#373737"
    gradient_end: str = "#2C2C2C"

    mc_stone: str = "#8B8B8B"
    mc_dirt: str = "#8B6B47"
    mc_grass: str = "#558B2F"
    mc_wood: str = "#6B4226"
    mc_diamond: str = "#55FFFF"
    mc_gold: str = "#FFAA00"
    mc_iron: str = "#D4D4D4"
    mc_coal: str = "#333333"
    mc_emerald: str = "#17DD62"
    mc_redstone: str = "#FF0000"


# 单例主题实例
THEME = ThemeColors()

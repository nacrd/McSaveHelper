"""Minecraft-style theme colors and border utilities"""
from dataclasses import dataclass
import flet as ft


@dataclass(frozen=True)
class ThemeColors:
    """Minecraft-inspired color palette"""
    # Background colors
    bg_primary: str = "#2B2B2B"
    bg_secondary: str = "#1C1C1C"
    bg_card: str = "#383838"
    bg_card_hover: str = "#484848"
    
    # Border colors - Minecraft beveled style
    border_light: str = "#A0A0A0"      # Top/left highlight
    border_dark: str = "#1A1A1A"       # Bottom/right shadow
    border_standard: str = "#5A5A5A"
    border_subtle: str = "#3F3F3F"
    
    # Accent colors
    accent: str = "#55FF55"
    accent_hover: str = "#7AFF7A"
    
    # Status colors
    success: str = "#55FF55"
    warning: str = "#FFAA00"
    error: str = "#FF5555"
    info: str = "#55AAFF"
    
    # Text colors
    text_primary: str = "#FFFFFF"
    text_secondary: str = "#AAAAAA"
    text_muted: str = "#707070"
    text_disabled: str = "#4A4A4A"
    
    # Terminal colors
    terminal_green: str = "#55FF55"
    terminal_yellow: str = "#FFAA00"
    terminal_red: str = "#FF5555"
    terminal_blue: str = "#5599FF"
    terminal_cyan: str = "#55FFFF"
    terminal_purple: str = "#AA55FF"
    
    # Minecraft block colors
    mc_stone: str = "#7D7D7D"
    mc_dirt: str = "#96651B"
    mc_grass: str = "#79C05A"
    mc_wood: str = "#9C6F3C"
    mc_diamond: str = "#5DFDFE"
    mc_gold: str = "#FFD700"
    mc_iron: str = "#D8D8D8"
    mc_coal: str = "#343434"
    mc_emerald: str = "#17DD62"
    mc_redstone: str = "#DD0000"
    mc_obsidian: str = "#0F0F1E"
    
    # Effects
    shadow: str = "rgba(0, 0, 0, 0.6)"
    
    # Backward compatibility aliases
    border_tertiary: str = "#A0A0A0"  # Alias for border_light
    accent_light: str = "#7AFF7A"     # Alias for accent_hover
    success_light: str = "#7AFF7A"    # Alias for accent_hover
    warning_light: str = "#FFCC44"    # Lighter warning
    error_light: str = "#FF7777"      # Lighter error
    text_quaternary: str = "#4A4A4A"  # Alias for text_disabled
    log_bg: str = "#1C1C1C"           # Alias for bg_secondary
    log_border: str = "#3F3F3F"       # Alias for border_subtle


def mc_border(width: int = 2) -> ft.Border:
    """Create a Minecraft-style beveled border (light top/left, dark bottom/right)"""
    return ft.Border(
        left=ft.BorderSide(width, THEME.border_light),
        top=ft.BorderSide(width, THEME.border_light),
        right=ft.BorderSide(width, THEME.border_dark),
        bottom=ft.BorderSide(width, THEME.border_dark),
    )


def mc_border_inverse(width: int = 2) -> ft.Border:
    """Create an inverted Minecraft-style border (pressed button effect)"""
    return ft.Border(
        left=ft.BorderSide(width, THEME.border_dark),
        top=ft.BorderSide(width, THEME.border_dark),
        right=ft.BorderSide(width, THEME.border_light),
        bottom=ft.BorderSide(width, THEME.border_light),
    )


def mc_shadow(offset: int = 4) -> ft.BoxShadow:
    """Create a Minecraft-style drop shadow"""
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=0,
        color=THEME.shadow,
        offset=ft.Offset(offset, offset),
    )


# Global theme instance
THEME = ThemeColors()

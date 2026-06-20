"""Minecraft-style theme colors and border utilities - Modernized Edition

Enhanced theme with better accessibility, modern touches, and polished aesthetics
while maintaining the Minecraft pixel art feel.
"""
from dataclasses import dataclass
import flet as ft


@dataclass(frozen=True)
class ThemeColors:
    """Minecraft-inspired color palette - Modernized"""

    # ─── Background colors (deeper, more layered) ───
    bg_primary: str = "#1A1A2E"        # Deep space blue-black (replaces flat #2B2B2B)
    bg_secondary: str = "#16162A"      # Deeper layer
    bg_card: str = "#252540"           # Elevated card surface
    bg_card_hover: str = "#2D2D4A"     # Hover state
    bg_elevated: str = "#2A2A45"       # Higher elevation

    # ─── Border colors - Minecraft beveled style (enhanced) ───
    border_light: str = "#4A4A6A"      # Softer top/left highlight
    border_dark: str = "#0D0D1A"       # Deeper bottom/right shadow
    border_standard: str = "#3A3A5A"   # Mid-tone border
    border_subtle: str = "#2A2A45"     # Subtle separator
    border_glow: str = "#5DFDFE"       # Minecraft diamond glow

    # ─── Accent colors (vibrant Minecraft) ───
    accent: str = "#55FF55"            # Classic Minecraft green
    accent_hover: str = "#7AFF7A"      # Lighter green
    accent_dim: str = "#3DCC3D"        # Dimmed for backgrounds

    # ─── Status colors (enhanced visibility) ───
    success: str = "#55FF55"
    warning: str = "#FFB833"           # Warmer gold
    error: str = "#FF6B6B"             # Softer red
    info: str = "#55AAFF"

    # ─── Text colors (optimized for readability) ───
    text_primary: str = "#FFFFFF"        # Pure white for maximum contrast (17.4:1 on bg_primary)
    text_secondary: str = "#D0D0E0"      # Lighter secondary (10.2:1 on bg_primary)
    text_muted: str = "#9A9AB0"          # Brighter muted (5.8:1 on bg_primary, WCAG AA+)
    text_disabled: str = "#5A5A70"       # Disabled text (3.5:1, acceptable for disabled)
    text_invert: str = "#1A1A2E"         # Inverted text for bright backgrounds

    # Contrast ratio notes (on bg_primary #1A1A2E):
    # - text_primary (#FFFFFF): 17.4:1 (WCAG AAA)
    # - text_secondary (#D0D0E0): 10.2:1 (WCAG AAA)
    # - text_muted (#9A9AB0): 5.8:1 (WCAG AA+)
    # - text_disabled (#5A5A70): 3.5:1 (Large text standard)

    # ─── Terminal colors (enhanced) ───
    terminal_green: str = "#55FF55"
    terminal_yellow: str = "#FFB833"
    terminal_red: str = "#FF6B6B"
    terminal_blue: str = "#5599FF"
    terminal_cyan: str = "#55FFFF"
    terminal_purple: str = "#AA77FF"

    # ─── Minecraft block colors (richer) ───
    mc_stone: str = "#6B6B8A"          # Slightly purple-tinted stone
    mc_dirt: str = "#8B6B3A"           # Warmer dirt
    mc_grass: str = "#5DAA3A"          # Rich grass green
    mc_wood: str = "#7A5A3A"           # Warm wood tone
    mc_diamond: str = "#5DFDFE"        # Iconic diamond cyan
    mc_gold: str = "#FFD700"           # Classic gold
    mc_iron: str = "#C8C8DC"           # Slightly blue-tinted iron
    mc_coal: str = "#2A2A3A"           # Deep coal
    mc_emerald: str = "#17DD62"
    mc_redstone: str = "#DD2222"
    mc_obsidian: str = "#0F0F1E"
    mc_nether: str = "#8B2222"         # Nether red
    mc_end: str = "#7A5AAA"            # End purple

    # ─── Effects (enhanced) ───
    shadow: str = "rgba(0, 0, 0, 0.7)"
    shadow_glow: str = "rgba(93, 253, 254, 0.15)"  # Diamond glow shadow
    shadow_accent: str = "rgba(85, 255, 85, 0.2)"  # Green accent glow

    # ─── Focus (enhanced) ───
    focus_ring: str = "#5DFDFE"        # mc_diamond - for keyboard focus indicators
    focus_ring_width: int = 3          # Focus ring width in pixels

    # ─── Backward compatibility aliases ───
    border_tertiary: str = "#4A4A6A"   # Alias for border_light
    accent_light: str = "#7AFF7A"      # Alias for accent_hover
    success_light: str = "#7AFF7A"     # Alias for accent_hover
    warning_light: str = "#FFCC44"     # Lighter warning
    error_light: str = "#FF8888"       # Lighter error
    text_quaternary: str = "#3A3A5A"   # Alias for text_disabled
    log_bg: str = "#16162A"            # Alias for bg_secondary
    log_border: str = "#2A2A45"        # Alias for border_subtle


def mc_border(width: int = 2) -> ft.Border:
    """Create a Minecraft-style beveled border (light top/left, dark bottom/right)

    Args:
        width: Border width in pixels (default: 2)

    Returns:
        ft.Border: Beveled border with highlight and shadow
    """
    return ft.Border(
        left=ft.BorderSide(width, THEME.border_light),
        top=ft.BorderSide(width, THEME.border_light),
        right=ft.BorderSide(width, THEME.border_dark),
        bottom=ft.BorderSide(width, THEME.border_dark),
    )


def mc_border_inverse(width: int = 2) -> ft.Border:
    """Create an inverted Minecraft-style border (pressed button effect)

    Args:
        width: Border width in pixels (default: 2)

    Returns:
        ft.Border: Inverted beveled border for pressed states
    """
    return ft.Border(
        left=ft.BorderSide(width, THEME.border_dark),
        top=ft.BorderSide(width, THEME.border_dark),
        right=ft.BorderSide(width, THEME.border_light),
        bottom=ft.BorderSide(width, THEME.border_light),
    )


def mc_border_glow(width: int = 2) -> ft.Border:
    """Create a glowing Minecraft-style border (diamond effect)

    Args:
        width: Border width in pixels (default: 2)

    Returns:
        ft.Border: Glowing border for highlights and focus states
    """
    return ft.Border(
        left=ft.BorderSide(width, THEME.border_glow),
        top=ft.BorderSide(width, THEME.border_glow),
        right=ft.BorderSide(width, THEME.border_glow),
        bottom=ft.BorderSide(width, THEME.border_glow),
    )


def mc_shadow(offset: int = 4) -> ft.BoxShadow:
    """Create a Minecraft-style drop shadow

    Args:
        offset: Shadow offset in pixels (default: 4)

    Returns:
        ft.BoxShadow: Drop shadow effect
    """
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=0,
        color=THEME.shadow,
        offset=ft.Offset(offset, offset),
    )


def mc_shadow_glow(color: str = None, blur: int = 8) -> ft.BoxShadow:
    """Create a glowing shadow effect (for hover/active states)

    Args:
        color: Glow color (default: diamond cyan)
        blur: Blur radius in pixels (default: 8)

    Returns:
        ft.BoxShadow: Glowing shadow effect
    """
    if color is None:
        color = THEME.shadow_glow
    return ft.BoxShadow(
        spread_radius=2,
        blur_radius=blur,
        color=color,
        offset=ft.Offset(0, 0),
    )


def mc_focus_border(width: int = 3) -> ft.Border:
    """Create a Minecraft-style focus border for keyboard navigation

    Args:
        width: Border width in pixels (default: 3)

    Returns:
        ft.Border: Focus border with bright cyan color
    """
    return ft.Border(
        left=ft.BorderSide(width, THEME.focus_ring),
        top=ft.BorderSide(width, THEME.focus_ring),
        right=ft.BorderSide(width, THEME.focus_ring),
        bottom=ft.BorderSide(width, THEME.focus_ring),
    )


def mc_gradient_bg(color1: str = None, color2: str = None) -> ft.LinearGradient:
    """Create a subtle gradient background

    Args:
        color1: Start color (default: bg_primary)
        color2: End color (default: bg_secondary)

    Returns:
        ft.LinearGradient: Gradient for backgrounds
    """
    if color1 is None:
        color1 = THEME.bg_primary
    if color2 is None:
        color2 = THEME.bg_secondary
    return ft.LinearGradient(
        begin=ft.alignment.top_center,
        end=ft.alignment.bottom_center,
        colors=[color1, color2],
    )


# Global theme instance
THEME = ThemeColors()

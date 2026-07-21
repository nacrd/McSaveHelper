"""Minecraft-style theme system with dark/light mode support

Provides a ThemeManager singleton for runtime theme switching,
ThemeColors dataclass for two complete color palettes, and
utility functions for Minecraft-style borders, shadows, and effects.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional
import flet as ft


@dataclass(frozen=True)
class ThemeColors:
    """Minecraft-inspired color palette"""

    # ─── Background colors ───
    bg_primary: str = ""
    bg_secondary: str = ""
    bg_card: str = ""
    bg_card_hover: str = ""
    bg_elevated: str = ""

    # ─── Border colors - Minecraft beveled style ───
    border_light: str = ""
    border_dark: str = ""
    border_standard: str = ""
    border_subtle: str = ""
    border_glow: str = ""

    # ─── Accent colors ───
    accent: str = ""
    accent_hover: str = ""
    accent_dim: str = ""

    # ─── Status colors ───
    success: str = ""
    warning: str = ""
    error: str = ""
    info: str = ""

    # ─── Text colors ───
    text_primary: str = ""
    text_secondary: str = ""
    text_muted: str = ""
    text_disabled: str = ""
    text_invert: str = ""

    # ─── Terminal colors ───
    terminal_green: str = ""
    terminal_yellow: str = ""
    terminal_red: str = ""
    terminal_blue: str = ""
    terminal_cyan: str = ""
    terminal_purple: str = ""

    # ─── Minecraft block colors ───
    mc_stone: str = ""
    mc_dirt: str = ""
    mc_grass: str = ""
    mc_wood: str = ""
    mc_diamond: str = ""
    mc_gold: str = ""
    mc_iron: str = ""
    mc_coal: str = ""
    mc_emerald: str = ""
    mc_redstone: str = ""
    mc_obsidian: str = ""
    mc_nether: str = ""
    mc_end: str = ""

    # ─── Effects ───
    shadow: str = ""
    shadow_glow: str = ""
    shadow_accent: str = ""

    # ─── Focus ───
    focus_ring: str = ""
    focus_ring_width: int = 3

    # ─── Backward compatibility aliases ───
    border_tertiary: str = ""
    accent_light: str = ""
    success_light: str = ""
    warning_light: str = ""
    error_light: str = ""
    text_quaternary: str = ""
    log_bg: str = ""
    log_border: str = ""

    # ─── Theme mode identifier ───
    mode: str = "dark"


# ════════════════════════════════════════════
#  Dark Theme
# ════════════════════════════════════════════

DARK_THEME = ThemeColors(
    # Neutral workspace surfaces
    bg_primary="#111513",
    bg_secondary="#171C19",
    bg_card="#1D231F",
    bg_card_hover="#252D28",
    bg_elevated="#29312C",
    # Quiet separators and focus treatment
    border_light="#3B463F",
    border_dark="#090C0A",
    border_standard="#647269",
    border_subtle="#3D4A42",
    border_glow="#63D5E5",
    # Product accent
    accent="#63C174",
    accent_hover="#78D28A",
    accent_dim="#438A52",
    # Status
    success="#3FBF8A",
    warning="#E5B454",
    error="#E06C75",
    info="#63D5E5",
    # Text
    text_primary="#F2F5F3",
    text_secondary="#C3CBC6",
    text_muted="#AAB7AF",
    text_disabled="#59635D",
    text_invert="#0E1510",
    # Terminal
    terminal_green="#78D28A",
    terminal_yellow="#E5B454",
    terminal_red="#E06C75",
    terminal_blue="#72A7E5",
    terminal_cyan="#63D5E5",
    terminal_purple="#B19CD9",
    # Minecraft blocks
    mc_stone="#58635D",
    mc_dirt="#715A45",
    mc_grass="#63C174",
    mc_wood="#202722",
    mc_diamond="#63D5E5",
    mc_gold="#E5B454",
    mc_iron="#AEB8B2",
    mc_coal="#171C19",
    mc_emerald="#50B86A",
    mc_redstone="#D75A64",
    mc_obsidian="#0A0D0B",
    mc_nether="#7F4148",
    mc_end="#786A91",
    # Effects
    shadow="rgba(0, 0, 0, 0.28)",
    shadow_glow="rgba(99, 213, 229, 0.14)",
    shadow_accent="rgba(99, 193, 116, 0.18)",
    # Focus
    focus_ring="#63D5E5",
    focus_ring_width=2,
    # Backward compat aliases
    border_tertiary="#3B463F",
    accent_light="#78D28A",
    success_light="#78D28A",
    warning_light="#F0C66B",
    error_light="#EA8991",
    text_quaternary="#59635D",
    log_bg="#0D110F",
    log_border="#28312B",
    # Mode
    mode="dark",
)


# ════════════════════════════════════════════
#  Light Theme (Minecraft parchment / survival book style)
# ════════════════════════════════════════════

LIGHT_THEME = ThemeColors(
    # Neutral daylight workspace surfaces
    bg_primary="#F3F6F4",
    bg_secondary="#E9EEEB",
    bg_card="#FFFFFF",
    bg_card_hover="#F0F5F1",
    bg_elevated="#FFFFFF",
    # Borders
    border_light="#D8E0DB",
    border_dark="#AEB9B2",
    border_standard="#7D8C82",
    border_subtle="#A8B5AD",
    border_glow="#168FA3",
    # Accents
    accent="#347A45",
    accent_hover="#408F53",
    accent_dim="#2C663A",
    # Status
    success="#147A5B",
    warning="#8A5A08",
    error="#B64049",
    info="#0B7182",
    # Text
    text_primary="#172019",
    text_secondary="#425047",
    text_muted="#59685F",
    text_disabled="#9CA7A0",
    text_invert="#FFFFFF",
    # Terminal
    terminal_green="#2A8A2A",
    terminal_yellow="#B07800",
    terminal_red="#CC3333",
    terminal_blue="#3366AA",
    terminal_cyan="#228888",
    terminal_purple="#7744AA",
    # Minecraft blocks — same iconic colors, adjusted for light bg
    mc_stone="#7D8981",
    mc_dirt="#785D47",
    mc_grass="#347A45",
    mc_wood="#E9EEEB",
    mc_diamond="#168FA3",
    mc_gold="#A86F12",
    mc_iron="#7D8981",
    mc_coal="#D8E0DB",
    mc_emerald="#2E8A4B",
    mc_redstone="#B64049",
    mc_obsidian="#172019",
    mc_nether="#8F4650",
    mc_end="#6F5A88",
    # Effects — softer shadows for light bg
    shadow="rgba(19, 32, 23, 0.10)",
    shadow_glow="rgba(22, 143, 163, 0.12)",
    shadow_accent="rgba(52, 122, 69, 0.12)",
    # Focus
    focus_ring="#168FA3",
    focus_ring_width=2,
    # Backward compat aliases
    border_tertiary="#7D8C82",
    accent_light="#408F53",
    success_light="#408F53",
    warning_light="#C58A2A",
    error_light="#CA5A63",
    text_quaternary="#9CA7A0",
    log_bg="#172019",
    log_border="#7D8C82",
    # Mode
    mode="light",
)


# ════════════════════════════════════════════
#  Theme Proxy (transparent attribute delegation)
# ════════════════════════════════════════════

class _ThemeProxy:
    """Proxy that delegates all attribute access to ThemeManager.current

    Existing code like `THEME.bg_primary` continues to work unchanged;
    the proxy resolves to whichever theme is currently active.
    """

    def __init__(self, get_current: Callable[[], ThemeColors]) -> None:
        object.__setattr__(self, '_get_current', get_current)

    def __getattr__(self, name: str):
        return getattr(self._get_current(), name)

    def __repr__(self) -> str:
        return repr(self._get_current())


# ════════════════════════════════════════════
#  ThemeManager (singleton)
# ════════════════════════════════════════════

class ThemeManager:
    """Manages dark/light theme switching at runtime.

    Usage:
        manager = ThemeManager()
        manager.set_mode("light")
        manager.toggle()

        # Access current theme colors via the module-level THEME proxy:
        from app.ui.theme import THEME
        print(THEME.bg_primary)  # always reflects the active theme
    """

    _instance: Optional["ThemeManager"] = None

    def __new__(cls) -> "ThemeManager":
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._initialized = False
            cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        """初始化单例主题表、默认模式与监听器列表。

        再次调用时为幂等空操作（单例已初始化则直接返回）。
        """
        if self._initialized:
            return
        self._themes = {
            "dark": DARK_THEME,
            "light": LIGHT_THEME,
        }
        self._mode: str = "dark"
        self._current: ThemeColors = DARK_THEME
        self._listeners: List[Callable[[str], None]] = []
        self._initialized = True

    @property
    def current(self) -> ThemeColors:
        """Return the active ThemeColors instance."""
        return self._current

    @property
    def mode(self) -> str:
        """Return the current theme mode string."""
        return self._mode

    def set_mode(self, mode: str) -> None:
        """Switch to a named theme mode.

        Args:
            mode: "dark" or "light"

        Raises:
            ValueError: If mode is not a recognized theme name.
        """
        mode = mode.lower()
        if mode not in self._themes:
            raise ValueError(
                f"Unknown theme mode '{mode}'; "
                f"available: {list(self._themes.keys())}"
            )
        if mode == self._mode:
            return
        self._mode = mode
        self._current = self._themes[mode]
        self._notify_listeners(mode)

    def toggle(self) -> str:
        """Toggle between dark and light themes.

        Returns:
            The new mode string after toggling.
        """
        new_mode = "light" if self._mode == "dark" else "dark"
        self.set_mode(new_mode)
        return new_mode

    def register_listener(self, callback: Callable[[str], None]) -> None:
        """Register a callback to be called when the theme changes.

        Args:
            callback: Function receiving the new mode string.
        """
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[str], None]) -> None:
        """Unregister a previously registered theme change listener."""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def _notify_listeners(self, mode: str) -> None:
        for cb in self._listeners:
            try:
                cb(mode)
            except Exception:
                pass


# ════════════════════════════════════════════
#  Module-level singletons
# ════════════════════════════════════════════

_theme_manager = ThemeManager()
THEME = _ThemeProxy(lambda: _theme_manager.current)


def get_theme_manager() -> ThemeManager:
    """Return the singleton ThemeManager instance."""
    return _theme_manager


# ════════════════════════════════════════════
#  Border utilities
# ════════════════════════════════════════════

def mc_border(width: int = 2) -> ft.Border:
    """Create a uniform border for workspace surfaces.

    Args:
        width: Border width in pixels (default: 2)

    Returns:
        ft.Border: Beveled border with highlight and shadow
    """
    return ft.Border.all(width, THEME.border_standard)


def mc_border_inverse(width: int = 2) -> ft.Border:
    """Create a stronger pressed-state border.

    Args:
        width: Border width in pixels (default: 2)

    Returns:
        ft.Border: Inverted beveled border for pressed states
    """
    return ft.Border.all(width, THEME.border_dark)


def mc_border_glow(width: int = 2) -> ft.Border:
    """Create a focus border.

    Args:
        width: Border width in pixels (default: 2)

    Returns:
        ft.Border: Glowing border for highlights and focus states
    """
    return ft.Border.all(width, THEME.border_glow)


# ════════════════════════════════════════════
#  Shadow utilities
# ════════════════════════════════════════════

def mc_shadow(offset: int = 4) -> ft.BoxShadow:
    """Create a soft elevation shadow.

    Args:
        offset: Shadow offset in pixels (default: 4)

    Returns:
        ft.BoxShadow: Drop shadow effect
    """
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=max(8, offset * 3),
        color=THEME.shadow,
        offset=ft.Offset(0, max(1, offset // 2)),
    )


def mc_shadow_glow(
    color: Optional[str] = None,
    blur: int = 8,
) -> ft.BoxShadow:
    """Create a glowing shadow effect (for hover/active states)

    Args:
        color: Glow color (default: diamond glow)
        blur: Blur radius in pixels (default: 8)

    Returns:
        ft.BoxShadow: Glowing shadow effect
    """
    selected_color = color or THEME.shadow_glow
    return ft.BoxShadow(
        spread_radius=2,
        blur_radius=blur,
        color=selected_color,
        offset=ft.Offset(0, 0),
    )


# ════════════════════════════════════════════
#  Focus utilities
# ════════════════════════════════════════════

def mc_focus_border(width: int = 3) -> ft.Border:
    """Create a Minecraft-style focus border for keyboard navigation

    Args:
        width: Border width in pixels (default: 3)

    Returns:
        ft.Border: Focus border with highlight color
    """
    return ft.Border(
        left=ft.BorderSide(width, THEME.focus_ring),
        top=ft.BorderSide(width, THEME.focus_ring),
        right=ft.BorderSide(width, THEME.focus_ring),
        bottom=ft.BorderSide(width, THEME.focus_ring),
    )


# ════════════════════════════════════════════
#  Gradient utilities
# ════════════════════════════════════════════

def mc_gradient_bg(
    color1: Optional[str] = None,
    color2: Optional[str] = None,
) -> ft.LinearGradient:
    """Create a subtle gradient background

    Args:
        color1: Start color (default: bg_primary)
        color2: End color (default: bg_secondary)

    Returns:
        ft.LinearGradient: Gradient for backgrounds
    """
    start_color = color1 or THEME.bg_primary
    end_color = color2 or THEME.bg_secondary
    return ft.LinearGradient(
        begin=ft.Alignment(0, -1),
        end=ft.Alignment(0, 1),
        colors=[start_color, end_color],
    )

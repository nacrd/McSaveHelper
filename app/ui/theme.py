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
    # Backgrounds
    bg_primary="#1B1B2F",
    bg_secondary="#16162A",
    bg_card="#272745",
    bg_card_hover="#2F2F4D",
    bg_elevated="#2C2C48",
    # Borders
    border_light="#4A4A6A",
    border_dark="#0D0D1A",
    border_standard="#3A3A5A",
    border_subtle="#2A2A45",
    border_glow="#5DFDFE",
    # Accents
    accent="#55FF55",
    accent_hover="#7AFF7A",
    accent_dim="#3DCC3D",
    # Status
    success="#55FF55",
    warning="#FFB833",
    error="#FF6B6B",
    info="#55AAFF",
    # Text
    text_primary="#FFFFFF",
    text_secondary="#D0D0E0",
    text_muted="#9A9AB0",
    text_disabled="#5A5A70",
    text_invert="#1B1B2F",
    # Terminal
    terminal_green="#55FF55",
    terminal_yellow="#FFB833",
    terminal_red="#FF6B6B",
    terminal_blue="#5599FF",
    terminal_cyan="#55FFFF",
    terminal_purple="#AA77FF",
    # Minecraft blocks
    mc_stone="#6B6B8A",
    mc_dirt="#8B6B3A",
    mc_grass="#5DAA3A",
    mc_wood="#7A5A3A",
    mc_diamond="#5DFDFE",
    mc_gold="#FFD700",
    mc_iron="#C8C8DC",
    mc_coal="#2A2A3A",
    mc_emerald="#17DD62",
    mc_redstone="#DD2222",
    mc_obsidian="#0F0F1E",
    mc_nether="#8B2222",
    mc_end="#7A5AAA",
    # Effects
    shadow="rgba(0, 0, 0, 0.65)",
    shadow_glow="rgba(93, 253, 254, 0.15)",
    shadow_accent="rgba(85, 255, 85, 0.2)",
    # Focus
    focus_ring="#5DFDFE",
    focus_ring_width=3,
    # Backward compat aliases
    border_tertiary="#4A4A6A",
    accent_light="#7AFF7A",
    success_light="#7AFF7A",
    warning_light="#FFCC44",
    error_light="#FF8888",
    text_quaternary="#3A3A5A",
    log_bg="#16162A",
    log_border="#2A2A45",
    # Mode
    mode="dark",
)


# ════════════════════════════════════════════
#  Light Theme (Minecraft parchment / survival book style)
# ════════════════════════════════════════════

LIGHT_THEME = ThemeColors(
    # Backgrounds — warm parchment palette
    bg_primary="#F0EBE0",
    bg_secondary="#E5DFD2",
    bg_card="#FFFFFF",
    bg_card_hover="#F8F6F0",
    bg_elevated="#FFFFFF",
    # Borders — earthy tones
    border_light="#D8D0C0",
    border_dark="#A09880",
    border_standard="#C0B8A8",
    border_subtle="#E0D8C8",
    border_glow="#3AB8E8",
    # Accents
    accent="#3AAA3A",
    accent_hover="#4CC84C",
    accent_dim="#2A8A2A",
    # Status
    success="#3AAA3A",
    warning="#D4920A",
    error="#CC3333",
    info="#3388CC",
    # Text
    text_primary="#2C2416",
    text_secondary="#5A4E3A",
    text_muted="#8A7E6A",
    text_disabled="#B0A890",
    text_invert="#FFFFFF",
    # Terminal
    terminal_green="#2A8A2A",
    terminal_yellow="#B07800",
    terminal_red="#CC3333",
    terminal_blue="#3366AA",
    terminal_cyan="#228888",
    terminal_purple="#7744AA",
    # Minecraft blocks — same iconic colors, adjusted for light bg
    mc_stone="#8A8A9A",
    mc_dirt="#8B6B3A",
    mc_grass="#4A9A30",
    mc_wood="#7A5A3A",
    mc_diamond="#2AB8D0",
    mc_gold="#CC9900",
    mc_iron="#8A8A98",
    mc_coal="#555555",
    mc_emerald="#10BB55",
    mc_redstone="#CC2222",
    mc_obsidian="#3A3A4A",
    mc_nether="#8B2222",
    mc_end="#7A5AAA",
    # Effects — softer shadows for light bg
    shadow="rgba(0, 0, 0, 0.10)",
    shadow_glow="rgba(58, 184, 232, 0.12)",
    shadow_accent="rgba(58, 170, 58, 0.12)",
    # Focus
    focus_ring="#3AB8E8",
    focus_ring_width=3,
    # Backward compat aliases
    border_tertiary="#D8D0C0",
    accent_light="#4CC84C",
    success_light="#4CC84C",
    warning_light="#E0A820",
    error_light="#DD5555",
    text_quaternary="#B0A890",
    log_bg="#E5DFD2",
    log_border="#E0D8C8",
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


# ════════════════════════════════════════════
#  Shadow utilities
# ════════════════════════════════════════════

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

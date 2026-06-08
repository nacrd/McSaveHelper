"""Minecraft-style progress bar components with animations"""
from typing import Optional

import flet as ft

from app.ui.theme import THEME, mc_border


class McProgressBar(ft.Container):
    """Minecraft-style progress bar with decorative border and animations

    Features:
    - Beveled border decoration
    - Smooth progress animations
    - Optional percentage text
    - Customizable colors
    """

    def __init__(
        self,
        value: float = 0.0,
        width: Optional[int] = None,
        height: int = 12,
        color: str = THEME.mc_diamond,
        bgcolor: str = THEME.bg_secondary,
        show_percentage: bool = False,
        animated: bool = True,
    ) -> None:
        self._value = value
        self._color = color
        self._bgcolor = bgcolor
        self._show_percentage = show_percentage
        self._animated = animated

        # Create inner progress bar
        self._progress_bar = ft.ProgressBar(
            value=value,
            color=color,
            bgcolor=bgcolor,
            height=height - 4,  # Account for border
            border_radius=0,
            bar_height=height - 4,
        )

        # Percentage text (optional)
        self._percentage_text = ft.Text(
            self._format_percentage(value),
            size=10,
            color=THEME.text_primary,
            weight=ft.FontWeight.BOLD,
            font_family="monospace",
            visible=show_percentage,
        )

        # Build container with decorative border
        content = ft.Stack([
            # Background layer
            ft.Container(
                bgcolor=bgcolor,
                height=height,
            ),
            # Progress bar layer
            ft.Container(
                content=self._progress_bar,
                padding=ft.Padding(left=2, right=2, top=2, bottom=2),
            ),
            # Percentage text layer (centered)
            ft.Container(
                content=self._percentage_text,
                alignment=ft.alignment.Alignment(0, 0),
                visible=show_percentage,
            ) if show_percentage else ft.Container(),
            # Decorative border layer
            ft.Container(
                border=mc_border(2),
                height=height,
            ),
        ])

        super().__init__(
            content=content,
            width=width,
            height=height,
            bgcolor=THEME.bg_card,
            border_radius=0,
        )

    def _format_percentage(self, value: float) -> str:
        """Format percentage value as string"""
        return f"{int(value * 100)}%"

    @property
    def value(self) -> float:
        """Get current progress value"""
        return self._value

    @value.setter
    def value(self, new_value: float) -> None:
        """Set progress value with animation (compatibility with native ProgressBar)

        Args:
            new_value: Progress value (0.0 to 1.0)
        """
        self.set_value(new_value)

    def set_value(self, value: float) -> None:
        """Set progress value with animation

        Args:
            value: Progress value (0.0 to 1.0)
        """
        self._value = max(0.0, min(1.0, value))
        self._progress_bar.value = self._value
        if self._show_percentage:
            self._percentage_text.value = self._format_percentage(self._value)
        try:
            self.update()
        except Exception:
            pass

    def set_color(self, color: str) -> None:
        """Set progress bar color

        Args:
            color: Hex color string
        """
        self._color = color
        self._progress_bar.color = color
        try:
            self.update()
        except Exception:
            pass

    def reset(self) -> None:
        """Reset progress to 0"""
        self.set_value(0.0)

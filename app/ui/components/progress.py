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


class McProgressIndicator(ft.Container):
    """Minecraft-style progress indicator with icon and text
    
    Features:
    - Custom icon decoration
    - Status text display
    - Progress bar integration
    """
    
    def __init__(
        self,
        title: str = "进度",
        icon: str = "⛏",
        width: Optional[int] = None,
    ) -> None:
        self._title = title
        self._icon = icon
        
        # Create progress bar
        self._progress_bar = McProgressBar(
            value=0.0,
            width=width,
            show_percentage=True,
        )
        
        # Status text
        self._status_text = ft.Text(
            "就绪",
            size=12,
            color=THEME.mc_gold,
            weight=ft.FontWeight.BOLD,
            font_family="monospace",
        )
        
        # Build layout
        header = ft.Row([
            ft.Container(
                content=ft.Text(icon, size=14, color=THEME.text_primary),
                width=24,
                height=24,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.mc_grass,
                border=mc_border(1),
            ),
            ft.Text(
                title,
                size=14,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
                font_family="monospace",
            ),
            ft.Container(expand=True),
            self._status_text,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        
        content = ft.Column([
            header,
            ft.Container(height=8),
            self._progress_bar,
        ], spacing=0)
        
        super().__init__(
            content=content,
            width=width,
            padding=ft.Padding(left=16, right=16, top=12, bottom=12),
            bgcolor=THEME.bg_card,
            border=mc_border(2),
        )
    
    def set_progress(self, value: float, status: Optional[str] = None) -> None:
        """Set progress value and optional status text
        
        Args:
            value: Progress value (0.0 to 1.0)
            status: Optional status text
        """
        self._progress_bar.set_value(value)
        if status:
            self._status_text.value = status
            try:
                self._status_text.update()
            except Exception:
                pass
    
    def set_status(self, status: str) -> None:
        """Set status text only
        
        Args:
            status: Status text
        """
        self._status_text.value = status
        try:
            self._status_text.update()
        except Exception:
            pass
    
    def set_color(self, color: str) -> None:
        """Set progress bar color
        
        Args:
            color: Hex color string
        """
        self._progress_bar.set_color(color)
    
    def reset(self) -> None:
        """Reset progress and status"""
        self._progress_bar.reset()
        self._status_text.value = "就绪"
        try:
            self.update()
        except Exception:
            pass
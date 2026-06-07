"""Minecraft-style loading animation components"""
from typing import Optional

import flet as ft

from app.ui.theme import THEME, mc_border


class McLoadingSpinner(ft.Container):
    """Minecraft-style loading spinner with rotating animation
    
    Features:
    - Diamond-colored rotating icon
    - Decorative border
    - Optional status text
    - Smooth rotation animation
    """
    
    def __init__(
        self,
        size: int = 32,
        color: str = THEME.mc_diamond,
        show_text: bool = False,
        text: str = "加载中...",
    ) -> None:
        self._size = size
        self._color = color
        self._show_text = show_text
        self._text = text
        
        # Create rotating icon
        self._spinner_icon = ft.Icon(
            ft.Icons.RESTORE,
            size=size,
            color=color,
            rotate=0,
            animate_rotation=ft.Animation(1000, "linear"),
        )
        
        # Status text (optional)
        self._status_text = ft.Text(
            text,
            size=12,
            color=THEME.text_secondary,
            font_family="monospace",
            visible=show_text,
        )
        
        # Build content
        if show_text:
            content = ft.Column([
                ft.Container(
                    content=self._spinner_icon,
                    alignment=ft.alignment.Alignment(0, 0),
                    width=size + 20,
                    height=size + 20,
                ),
                ft.Container(height=8),
                self._status_text,
            ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        else:
            content = ft.Container(
                content=self._spinner_icon,
                alignment=ft.alignment.Alignment(0, 0),
                width=size + 16,
                height=size + 16,
            )
        
        super().__init__(
            content=content,
            bgcolor=THEME.bg_card,
            border=mc_border(2),
            padding=ft.Padding(left=16, right=16, top=16, bottom=16) if show_text else ft.Padding(left=8, right=8, top=8, bottom=8),
            alignment=ft.alignment.Alignment(0, 0),
        )
    
    def set_color(self, color: str) -> None:
        """Set spinner color
        
        Args:
            color: Hex color string
        """
        self._color = color
        self._spinner_icon.color = color
        try:
            self._spinner_icon.update()
        except Exception:
            pass
    
    def set_text(self, text: str) -> None:
        """Set status text
        
        Args:
            text: Status text
        """
        self._text = text
        self._status_text.value = text
        try:
            self._status_text.update()
        except Exception:
            pass
    
    def start(self) -> None:
        """Start rotation animation"""
        self._spinner_icon.rotate = ft.Rotate(angle=360)
        try:
            self._spinner_icon.update()
        except Exception:
            pass
    
    def stop(self) -> None:
        """Stop rotation animation"""
        self._spinner_icon.rotate = ft.Rotate(angle=0)
        try:
            self._spinner_icon.update()
        except Exception:
            pass


class McLoadingOverlay(ft.Container):
    """Full-screen loading overlay with spinner and message
    
    Features:
    - Semi-transparent background
    - Centered spinner
    - Optional progress text
    - Easy show/hide methods
    """
    
    def __init__(
        self,
        page: ft.Page,
        message: str = "正在处理...",
        show_progress: bool = False,
    ) -> None:
        self._page = page
        self._message = message
        self._show_progress = show_progress
        
        # Create spinner
        self._spinner = McLoadingSpinner(
            size=48,
            show_text=True,
            text=message,
        )
        
        # Progress text (optional)
        self._progress_text = ft.Text(
            "",
            size=11,
            color=THEME.text_muted,
            font_family="monospace",
            visible=show_progress,
        )
        
        # Build overlay content
        content = ft.Column([
            self._spinner,
            ft.Container(height=12),
            self._progress_text,
        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        
        super().__init__(
            content=ft.Container(
                content=content,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.bg_card,
                border=mc_border(3),
                padding=ft.Padding(left=32, right=32, top=32, bottom=32),
                shadow=ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=20,
                    color=THEME.shadow,
                    offset=ft.Offset(0, 0),
                ),
            ),
            bgcolor="rgba(0, 0, 0, 0.7)",
            alignment=ft.alignment.Alignment(0, 0),
            visible=False,
            expand=True,
        )
    
    def show(self, message: Optional[str] = None) -> None:
        """Show loading overlay
        
        Args:
            message: Optional custom message
        """
        if message:
            self._message = message
            self._spinner.set_text(message)
        self.visible = True
        self._spinner.start()
        try:
            self._page.update()
        except Exception:
            pass
    
    def hide(self) -> None:
        """Hide loading overlay"""
        self.visible = False
        self._spinner.stop()
        try:
            self._page.update()
        except Exception:
            pass
    
    def set_progress(self, progress: str) -> None:
        """Set progress text
        
        Args:
            progress: Progress text (e.g., "50%")
        """
        self._progress_text.value = progress
        self._progress_text.visible = self._show_progress
        try:
            self._progress_text.update()
        except Exception:
            pass


class McBlockLoading(ft.Container):
    """Minecraft-style loading indicator using block animation
    
    Features:
    - Animated block icons (like Minecraft loading screen)
    - Multiple block types (dirt, stone, grass)
    - Sequential animation pattern
    """
    
    BLOCK_TYPES = ["🟫", "⬛", "🟩"]  # Dirt, Stone, Grass emoji
    
    def __init__(
        self,
        num_blocks: int = 5,
        block_size: int = 24,
        animation_speed: int = 200,
    ) -> None:
        self._num_blocks = num_blocks
        self._block_size = block_size
        self._animation_speed = animation_speed
        self._animation_task = None
        
        # Create animated blocks
        self._blocks: list[ft.Container] = []
        for i in range(num_blocks):
            block = ft.Container(
                content=ft.Text(
                    self.BLOCK_TYPES[i % len(self.BLOCK_TYPES)],
                    size=block_size,
                    color=THEME.text_primary,
                ),
                width=block_size + 8,
                height=block_size + 8,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.bg_secondary,
                border=mc_border(1),
                opacity=0.3,
            )
            self._blocks.append(block)
        
        # Build container
        content = ft.Row(
            self._blocks,
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        
        super().__init__(
            content=content,
            bgcolor=THEME.bg_card,
            border=mc_border(2),
            padding=ft.Padding(left=16, right=16, top=12, bottom=12),
        )
    
    def animate(self) -> None:
        """Start sequential block animation"""
        import asyncio
        
        async def _run_animation():
            try:
                while self._animation_task is not None:
                    for i, block in enumerate(self._blocks):
                        if self._animation_task is None:
                            break
                        # Highlight current block
                        block.opacity = 1.0
                        block.bgcolor = THEME.mc_grass
                        try:
                            block.update()
                        except Exception:
                            pass
                        
                        await asyncio.sleep(self._animation_speed / 1000)
                        
                        if self._animation_task is None:
                            break
                        # Reset block
                        block.opacity = 0.3
                        block.bgcolor = THEME.bg_secondary
                        try:
                            block.update()
                        except Exception:
                            pass
            except (asyncio.CancelledError, Exception):
                pass
        
        if self._animation_task is not None:
            self.stop()
        
        self._animation_task = asyncio.create_task(_run_animation())
    
    def stop(self) -> None:
        """Stop animation and reset all blocks"""
        # Cancel the animation task
        if self._animation_task is not None:
            self._animation_task.cancel()
            self._animation_task = None
        
        # Reset all blocks
        for block in self._blocks:
            block.opacity = 0.3
            block.bgcolor = THEME.bg_secondary
            try:
                block.update()
            except Exception:
                pass
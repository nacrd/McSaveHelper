"""Qt 全局动效系统：统一时长、缓动、打断与无障碍降级。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QAbstractAnimation,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


@dataclass(frozen=True)
class QtMotionTokens:
    """应用动效设计令牌，单位为毫秒。"""

    fast: int = 120
    standard: int = 180
    slow: int = 260


class QtAnimationSystem(QObject):
    """拥有全局 Qt 动画并保证同一控件只有一个进行中的动效。"""

    def __init__(
        self,
        *,
        reduced_motion: bool = False,
        tokens: Optional[QtMotionTokens] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        """初始化动效系统。

        Args:
            reduced_motion: 是否立即完成所有动效。
            tokens: 可替换的动效时长令牌。
            parent: Qt 生命周期父对象。
        """
        super().__init__(parent)
        self._reduced_motion = reduced_motion
        self._tokens = tokens or QtMotionTokens()
        self._active: dict[QWidget, QAbstractAnimation] = {}
        self._original_geometries: dict[QWidget, QRect] = {}

    @property
    def reduced_motion(self) -> bool:
        """返回是否已启用减少动效。"""
        return self._reduced_motion

    @property
    def active_count(self) -> int:
        """返回当前由系统持有的动画数量。"""
        return len(self._active)

    def set_reduced_motion(self, enabled: bool) -> None:
        """切换减少动效，并立即完成所有正在运行的动画。"""
        if enabled == self._reduced_motion:
            return
        self._reduced_motion = enabled
        if enabled:
            self.stop_all()

    def fade_in(
        self,
        widget: QWidget,
        *,
        duration_ms: Optional[int] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """让控件淡入并轻微滑入；新动效会安全替换旧动效。"""
        self.reveal(
            widget,
            start_opacity=0.0,
            offset_px=18,
            duration_ms=duration_ms,
            on_finished=on_finished,
        )

    def reveal(
        self,
        widget: QWidget,
        *,
        start_opacity: float = 0.15,
        offset_px: int = 0,
        duration_ms: Optional[int] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """以可配置透明度和位移呈现控件。"""
        self.stop(widget)
        if self._reduced_motion:
            if on_finished is not None:
                on_finished()
            return

        original_geometry = widget.geometry()
        if offset_px:
            self._original_geometries[widget] = original_geometry
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(start_opacity)
        widget.setGraphicsEffect(effect)
        opacity_animation = QPropertyAnimation(effect, b"opacity")
        opacity_animation.setStartValue(start_opacity)
        opacity_animation.setEndValue(1.0)
        animations: list[QPropertyAnimation] = [opacity_animation]
        if offset_px:
            offset_geometry = original_geometry.translated(offset_px, 0)
            widget.setGeometry(offset_geometry)
            geometry_animation = QPropertyAnimation(widget, b"geometry")
            geometry_animation.setStartValue(offset_geometry)
            geometry_animation.setEndValue(original_geometry)
            animations.append(geometry_animation)
        for animation in animations:
            animation.setDuration(duration_ms or self._tokens.standard)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        for animation in animations:
            group.addAnimation(animation)
        group.finished.connect(lambda: self._finish(widget, group, on_finished))
        self._active[widget] = group
        group.start()

    def fade_out(
        self,
        widget: QWidget,
        *,
        offset_px: int = -28,
        duration_ms: Optional[int] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """让控件向指定方向滑出并淡出。"""
        self.stop(widget)
        if self._reduced_motion:
            if on_finished is not None:
                on_finished()
            return
        original_geometry = widget.geometry()
        self._original_geometries[widget] = original_geometry
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(1.0)
        widget.setGraphicsEffect(effect)
        opacity_animation = QPropertyAnimation(effect, b"opacity")
        opacity_animation.setStartValue(1.0)
        opacity_animation.setEndValue(0.0)
        geometry_animation = QPropertyAnimation(widget, b"geometry")
        geometry_animation.setStartValue(original_geometry)
        geometry_animation.setEndValue(
            original_geometry.translated(offset_px, 0)
        )
        for animation in (opacity_animation, geometry_animation):
            animation.setDuration(duration_ms or self._tokens.standard)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        group.addAnimation(opacity_animation)
        group.addAnimation(geometry_animation)
        group.finished.connect(lambda: self._finish(widget, group, on_finished))
        self._active[widget] = group
        group.start()

    def animate_geometry(
        self,
        widget: QWidget,
        target: QRect,
        *,
        duration_ms: Optional[int] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """把控件位置和尺寸平滑过渡到目标矩形。"""
        self.stop(widget)
        if self._reduced_motion:
            widget.setGeometry(target)
            return
        animation = QPropertyAnimation(widget, b"geometry", self)
        animation.setDuration(duration_ms or self._tokens.standard)
        animation.setStartValue(widget.geometry())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(
            lambda: self._finish_geometry(
                widget,
                animation,
                target,
                on_finished,
            )
        )
        self._active[widget] = animation
        animation.start()

    def animate_width(
        self,
        widget: QWidget,
        target_width: int,
        *,
        duration_ms: Optional[int] = None,
    ) -> None:
        """缓动控件宽度，适用于侧栏等布局边界。"""
        self.stop(widget)
        if self._reduced_motion:
            widget.setFixedWidth(target_width)
            return
        current_width = max(widget.width(), widget.sizeHint().width())
        if current_width == target_width:
            widget.setFixedWidth(target_width)
            return
        if target_width > current_width:
            widget.setMinimumWidth(current_width)
            widget.setMaximumWidth(target_width)
            property_name = b"minimumWidth"
        else:
            widget.setMinimumWidth(target_width)
            widget.setMaximumWidth(current_width)
            property_name = b"maximumWidth"
        animation = QPropertyAnimation(widget, property_name, self)
        animation.setDuration(duration_ms or self._tokens.standard)
        animation.setStartValue(current_width)
        animation.setEndValue(target_width)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(
            lambda: self._finish_width(widget, animation, target_width)
        )
        self._active[widget] = animation
        animation.start()

    def stop(self, widget: QWidget) -> None:
        """停止控件动效并恢复完整可见状态。"""
        animation = self._active.pop(widget, None)
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        original_geometry = self._original_geometries.pop(widget, None)
        if original_geometry is not None:
            widget.setGeometry(original_geometry)
        effect = widget.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(1.0)
            widget.setGraphicsEffect(None)

    def stop_all(self) -> None:
        """停止系统拥有的全部动效。"""
        for widget in tuple(self._active):
            self.stop(widget)

    def dispose(self) -> None:
        """幂等释放全部动画。"""
        self.stop_all()

    def _finish(
        self,
        widget: QWidget,
        animation: QAbstractAnimation,
        on_finished: Optional[Callable[[], None]],
    ) -> None:
        if self._active.get(widget) is not animation:
            return
        self._active.pop(widget, None)
        widget.setGraphicsEffect(None)
        self._original_geometries.pop(widget, None)
        animation.deleteLater()
        if on_finished is not None:
            on_finished()

    def _finish_geometry(
        self,
        widget: QWidget,
        animation: QPropertyAnimation,
        target: QRect,
        on_finished: Optional[Callable[[], None]],
    ) -> None:
        if self._active.get(widget) is not animation:
            return
        self._active.pop(widget, None)
        widget.setGeometry(target)
        animation.deleteLater()
        if on_finished is not None:
            on_finished()

    def _finish_width(
        self,
        widget: QWidget,
        animation: QPropertyAnimation,
        target_width: int,
    ) -> None:
        if self._active.get(widget) is not animation:
            return
        self._active.pop(widget, None)
        widget.setFixedWidth(target_width)
        animation.deleteLater()

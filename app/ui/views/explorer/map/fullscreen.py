"""Lifecycle controller for the region map fullscreen overlay."""
from __future__ import annotations

from typing import Callable, Optional, Tuple

import flet as ft

from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.delayed_scheduler import (
    DelayScheduler,
    ScheduledCall,
    UiDelayedScheduler,
)
from app.ui.icons import IconSet
from app.ui.theme import THEME, mc_border
from app.ui.utils import safe_update
from app.ui.views.explorer.map.mca_map_view import McaMapView


Translate = Callable[[str, str], str]


class MapFullscreenController:
    """在内嵌宿主与页面 overlay 之间迁移同一张地图控件。

    进入全屏时把 ``McaMapView`` 从 inline 容器卸下挂到 page.overlay；
    退出时动画还原尺寸与侧栏可见性。``dispose`` 幂等，可在页面销毁时调用。
    """

    def __init__(
        self,
        *,
        page: Optional[ft.Page],
        map_view: McaMapView,
        inline_host: ft.Container,
        side_panel: ft.Container,
        set_toggle_state: Callable[[bool], None],
        refresh: Callable[[], None],
        zoom_in: Callable[[], None],
        zoom_out: Callable[[], None],
        reset: Callable[[], None],
        translate: Optional[Translate] = None,
        schedule_delayed: Optional[DelayScheduler] = None,
    ) -> None:
        """绑定页面、地图与工具栏回调。

        Args:
            page: Flet 页面；None 时仅隐藏侧栏，不建 overlay。
            map_view: 可 resize 的地图视图。
            inline_host: 内嵌地图宿主容器。
            side_panel: 侧信息面板（全屏时隐藏）。
            set_toggle_state: 同步全屏按钮 UI 状态。
            refresh: 刷新地图。
            zoom_in: 放大。
            zoom_out: 缩小。
            reset: 重置视口。
            translate: 可选 ``(key, fallback) -> str`` 翻译函数。
            schedule_delayed: 可选 UI 延迟调度端口，主要用于测试替换。
        """
        self._page = page
        self._map_view = map_view
        self._inline_host = inline_host
        self._side_panel = side_panel
        self._set_toggle_state = set_toggle_state
        self._refresh = refresh
        self._zoom_in = zoom_in
        self._zoom_out = zoom_out
        self._reset = reset
        self._translate = translate or (lambda _key, fallback: fallback)
        self._schedule_delayed = schedule_delayed or UiDelayedScheduler(
            lambda: self._page,
        )
        self._overlay: Optional[ft.Container] = None
        self._body: Optional[ft.Container] = None
        self._inline_content: Optional[ft.Control] = None
        self._pre_fullscreen_size: Optional[Tuple[int, int]] = None
        self._pre_side_visible = True
        self._enter_call: Optional[ScheduledCall] = None
        self._exit_call: Optional[ScheduledCall] = None
        self._transition_generation = 0
        self.active = False

    def toggle(self) -> None:
        """在进入与退出全屏之间切换。"""
        if self.active:
            self.exit()
        else:
            self.enter()

    def enter(self) -> None:
        """进入全屏：卸下内嵌地图、创建 overlay 并调度进入动画。"""
        if self.active or self._overlay is not None:
            return
        self._transition_generation += 1
        generation = self._transition_generation
        self.active = True
        self._set_toggle_state(True)
        self._pre_side_visible = self._side_panel.visible is not False
        self._pre_fullscreen_size = (
            int(self._map_view.width or 900),
            int(self._map_view.height or 560),
        )
        self._inline_content = self._inline_host.content
        if self._page is None:
            self._side_panel.visible = False
            safe_update(self._side_panel)
            return

        width, height = self.window_size(self._page)
        bar_height = 48
        map_width = max(400, width)
        map_height = max(300, height - bar_height)
        self._detach_inline_map()
        self._resize_map(map_width, map_height, refit=True)
        self._body = self._build_map_body(map_width, map_height)
        self._overlay = self._build_overlay(
            width,
            height,
            bar_height,
            self._body,
        )
        try:
            self._page.overlay.append(self._overlay)
            self._page.update()
        except Exception:
            self._restore()
            return
        self._schedule_enter_animation(width, height, bar_height, generation)

    def exit(self) -> None:
        """播放退出动画并延迟还原到内嵌宿主。"""
        self._transition_generation += 1
        generation = self._transition_generation
        self._cancel_call(self._enter_call)
        self._enter_call = None
        overlay = self._overlay
        body = self._body
        if overlay is None or body is None:
            self._restore()
            return
        try:
            overlay.opacity = 0.0
            body.scale = 0.96
            body.opacity = 0.0
        except Exception:
            # UI best-effort: overlay may already be disposed.
            pass
        safe_update(overlay)
        safe_update(body)
        self._cancel_call(self._exit_call)
        try:
            self._exit_call = self._schedule_delayed(
                0.18,
                lambda: self._restore_on_ui(generation),
            )
        except Exception:
            self._exit_call = None
            self._restore()
            raise
        if self._exit_call is None:
            self._restore_on_ui(generation)

    def dispose(self) -> None:
        """取消定时器并立即还原；可重复调用。"""
        self._transition_generation += 1
        self._cancel_call(self._enter_call)
        self._cancel_call(self._exit_call)
        self._enter_call = None
        self._exit_call = None
        self._restore()

    @staticmethod
    def window_size(page: ft.Page) -> Tuple[int, int]:
        """读取页面/窗口尺寸并施加合理下限。

        Args:
            page: Flet 页面。

        Returns:
            ``(width, height)`` 像素尺寸。
        """
        width = int(getattr(page, "width", 0) or 0)
        height = int(getattr(page, "height", 0) or 0)
        window = getattr(page, "window", None)
        if window is not None:
            width = max(width, int(getattr(window, "width", 0) or 0))
            height = max(height, int(getattr(window, "height", 0) or 0))
        return max(800, width or 1100), max(600, height or 800)

    def _detach_inline_map(self) -> None:
        if self._inline_content is None:
            self._inline_content = self._inline_host.content
        self._inline_host.content = ft.Container(
            content=ft.Text(
                self._translate("map.fullscreen_active", "地图全屏中..."),
                size=13,
                color=THEME.text_muted,
            ),
            alignment=ft.Alignment(0, 0),
            expand=True,
            bgcolor=THEME.bg_secondary,
        )
        safe_update(self._inline_host)

    def _build_map_body(self, width: int, height: int) -> ft.Container:
        return ft.Container(
            content=self._map_view,
            width=width,
            height=height,
            bgcolor=THEME.bg_secondary,
            padding=0,
            scale=0.96,
            opacity=0.0,
            animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT_CUBIC),
            animate_opacity=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

    def _build_overlay(
        self,
        width: int,
        height: int,
        bar_height: int,
        body: ft.Container,
    ) -> ft.Container:
        top_bar = ft.Container(
            content=self._build_overlay_actions(),
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
            height=bar_height,
            bgcolor=THEME.bg_card,
            border=mc_border(2),
        )
        return ft.Container(
            content=ft.Column([top_bar, body], spacing=0, tight=True),
            left=0,
            top=0,
            width=width,
            height=height,
            padding=0,
            bgcolor="#0B120B",
            opacity=0.0,
            animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        )

    def _build_overlay_actions(self) -> ft.Row:
        return ft.Row(
            [
                ft.Text(
                    self._translate("map.fullscreen_title", "区域地图 · 全屏"),
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Container(expand=True),
                btn_primary(
                    self._translate("map.refresh", "刷新地图"),
                    width=84,
                    on_click=lambda e: self._refresh(),
                ),
                btn_ghost(
                    "放大",
                    width=80,
                    icon=ft.Icons.ZOOM_IN,
                    on_click=lambda e: self._zoom_in(),
                ),
                btn_ghost(
                    "缩小",
                    width=80,
                    icon=ft.Icons.ZOOM_OUT,
                    on_click=lambda e: self._zoom_out(),
                ),
                btn_ghost(
                    "复位",
                    width=80,
                    icon=IconSet.REFRESH,
                    on_click=lambda e: self._reset(),
                ),
                btn_ghost(
                    self._translate("map.exit_fullscreen", "退出全屏"),
                    width=120,
                    on_click=lambda e: self.exit(),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _schedule_enter_animation(
        self,
        width: int,
        height: int,
        bar_height: int,
        generation: int,
    ) -> None:
        self._cancel_call(self._enter_call)

        try:
            self._enter_call = self._schedule_delayed(
                0.02,
                lambda: self._animate_in(width, height, bar_height, generation),
            )
        except Exception:
            self._enter_call = None
            self._restore()
            raise
        if self._enter_call is None:
            self._animate_in(width, height, bar_height, generation)

    def _animate_in(
        self,
        width: int,
        height: int,
        bar_height: int,
        generation: int,
    ) -> None:
        if generation != self._transition_generation:
            return
        self._enter_call = None
        overlay = self._overlay
        body = self._body
        if overlay is None or body is None or self._page is None:
            return
        measured_width, measured_height = self.window_size(self._page)
        if (measured_width, measured_height) != (width, height):
            overlay.width = measured_width
            overlay.height = measured_height
            map_width = max(400, measured_width)
            map_height = max(300, measured_height - bar_height)
            body.width = map_width
            body.height = map_height
            self._resize_map(map_width, map_height, refit=True)
        overlay.opacity = 1.0
        body.scale = 1.0
        body.opacity = 1.0
        safe_update(overlay)
        safe_update(body)

    def _restore_on_ui(self, generation: int) -> None:
        if generation != self._transition_generation:
            return
        self._restore()

    def _restore(self) -> None:
        self._transition_generation += 1
        self._cancel_call(self._enter_call)
        self._cancel_call(self._exit_call)
        self._enter_call = None
        self._exit_call = None
        if not self.active and self._overlay is None and self._inline_content is None:
            return
        overlay = self._overlay
        if self._page is not None and overlay is not None:
            try:
                if overlay in self._page.overlay:
                    self._page.overlay.remove(overlay)
                if self._page is not None:
                    self._page.update()
            except Exception:
                # UI best-effort: page/overlay may already be closing.
                pass
        self._overlay = None
        self._body = None
        self._inline_host.content = self._inline_content or self._map_view
        self._inline_content = None
        safe_update(self._inline_host)
        if self._pre_fullscreen_size is not None:
            width, height = self._pre_fullscreen_size
            self._resize_map(width, height, refit=False)
        self._side_panel.visible = self._pre_side_visible
        safe_update(self._side_panel)
        self.active = False
        self._set_toggle_state(False)

    def _resize_map(self, width: int, height: int, *, refit: bool) -> None:
        self._map_view.resize_map(width, height, refit=refit)

    @staticmethod
    def _cancel_call(call: Optional[ScheduledCall]) -> None:
        if call is not None:
            call.cancel()

"""Lifecycle controller for the region map fullscreen overlay."""
from __future__ import annotations

import threading
from typing import Callable, Optional, Tuple

import flet as ft

from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.theme import THEME, mc_border
from app.ui.utils import run_on_ui, safe_update
from app.ui.views.explorer.map.mca_map_view import McaMapView


Translate = Callable[[str, str], str]


class MapFullscreenController:
    """Move one map control between its inline host and a page overlay."""

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
    ) -> None:
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
        self._overlay: Optional[ft.Container] = None
        self._body: Optional[ft.Container] = None
        self._inline_content: Optional[ft.Control] = None
        self._pre_fullscreen_size: Optional[Tuple[int, int]] = None
        self._pre_side_visible = True
        self._enter_timer: Optional[threading.Timer] = None
        self._exit_timer: Optional[threading.Timer] = None
        self.active = False

    def toggle(self) -> None:
        if self.active:
            self.exit()
        else:
            self.enter()

    def enter(self) -> None:
        if self.active or self._overlay is not None:
            return
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
        self._schedule_enter_animation(width, height, bar_height)

    def exit(self) -> None:
        self._cancel_timer(self._enter_timer)
        self._enter_timer = None
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
        self._cancel_timer(self._exit_timer)
        self._exit_timer = threading.Timer(0.18, self._restore_on_ui)
        self._exit_timer.daemon = True
        self._exit_timer.start()

    def dispose(self) -> None:
        self._cancel_timer(self._enter_timer)
        self._cancel_timer(self._exit_timer)
        self._enter_timer = None
        self._exit_timer = None
        self._restore()

    @staticmethod
    def window_size(page: ft.Page) -> Tuple[int, int]:
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
            content=ft.Row(
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
                        "🔍+",
                        width=52,
                        on_click=lambda e: self._zoom_in(),
                    ),
                    btn_ghost(
                        "🔍−",
                        width=52,
                        on_click=lambda e: self._zoom_out(),
                    ),
                    btn_ghost(
                        "🏠",
                        width=52,
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
            ),
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

    def _schedule_enter_animation(
        self,
        width: int,
        height: int,
        bar_height: int,
    ) -> None:
        self._cancel_timer(self._enter_timer)

        def animate() -> None:
            if self._page is None:
                return
            run_on_ui(
                self._page,
                self._animate_in,
                width,
                height,
                bar_height,
            )

        self._enter_timer = threading.Timer(0.02, animate)
        self._enter_timer.daemon = True
        self._enter_timer.start()

    def _animate_in(self, width: int, height: int, bar_height: int) -> None:
        self._enter_timer = None
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

    def _restore_on_ui(self) -> None:
        if self._page is None:
            self._restore()
        else:
            run_on_ui(self._page, self._restore)

    def _restore(self) -> None:
        self._cancel_timer(self._enter_timer)
        self._cancel_timer(self._exit_timer)
        self._enter_timer = None
        self._exit_timer = None
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
    def _cancel_timer(timer: Optional[threading.Timer]) -> None:
        if timer is not None:
            timer.cancel()

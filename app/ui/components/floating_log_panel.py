"""Floating log panel component — 可拖拽移动的悬浮球日志面板"""
import threading
from collections import deque
from typing import Any, Callable

import flet as ft

from app.ui.theme import THEME, mc_border, mc_shadow
from app.ui.icons import IconSet
from app.ui.utils import run_on_ui, safe_update
from app.ui.components.floating_position import (
    DragTracker,
    FloatingBounds,
    SharedPositionStore,
    clamp_position,
)


def _is_app_closing() -> bool:
    """检查应用是否正在关闭。"""
    try:
        from app.ui.utils import is_app_closing
        return is_app_closing()
    except Exception:
        # Import/state lookup best-effort during teardown.
        return False


class FloatingLogPanel(ft.Container):
    """可拖拽移动的悬浮球日志面板

    特性：
    - 悬浮球可自由拖拽移动
    - 面板可通过标题栏拖拽
    - 位置持久化保存
    - 自动滚动功能
    - 鼠标滚轮支持
    """

    DEFAULT_WIDTH = 380
    DEFAULT_HEIGHT = 280
    MAX_LINES = 300
    STORAGE_KEY = "floating_log_panel_position"

    def __init__(self, page: ft.Page, title: str = "日志") -> None:
        self._page = page
        self._title = title
        self._expanded = False
        self._auto_scroll = True
        self._offset_left = 50.0
        self._offset_top = 200.0
        self._drag = DragTracker()
        self._position_store = SharedPositionStore(page, self.STORAGE_KEY)
        self._pending_logs: deque[tuple[str, str]] = deque(
            maxlen=self.MAX_LINES
        )
        self._log_lock = threading.Lock()
        self._flush_timer: threading.Timer | None = None
        self._log_flush_scheduled = False
        self._flush_generation = 0

        self._log_col = ft.ListView(
            spacing=2,
            padding=0,
            expand=True,
            auto_scroll=True,
            on_scroll=self._on_scroll,
        )
        self._status_text = ft.Text(
            "",
            size=10,
            color=THEME.text_secondary,
        )
        self._build_header_controls(title)
        log_container = ft.Container(
            content=self._log_col,
            padding=ft.Padding(left=12, right=12, top=8, bottom=12),
            bgcolor=THEME.bg_primary,
            expand=True,
        )
        super().__init__(
            content=ft.Column(
                [
                    self._header_detector,
                    log_container,
                ],
                spacing=0,
                expand=True,
            ),
            width=self.DEFAULT_WIDTH,
            height=self.DEFAULT_HEIGHT,
            bgcolor=THEME.bg_card,
            border=mc_border(),
            border_radius=8,
            shadow=mc_shadow(6),
            visible=False,
            left=self._offset_left,
            top=self._offset_top,
        )
        self._load_position()

    def _build_header_controls(self, title: str) -> None:
        """Build title-bar buttons and drag detector."""
        self._auto_scroll_btn = self._header_icon_button(
            icon=ft.Icons.VERTICAL_ALIGN_BOTTOM,
            color=(
                THEME.terminal_green
                if self._auto_scroll
                else THEME.text_secondary
            ),
            on_click=self._toggle_auto_scroll,
            tooltip="自动滚动" if self._auto_scroll else "已暂停自动滚动",
        )
        self._clear_btn = self._header_icon_button(
            icon=ft.Icons.DELETE_OUTLINE,
            color=THEME.text_secondary,
            on_click=self._clear,
            tooltip="清除日志",
        )
        self._close_btn = self._header_icon_button(
            icon=IconSet.CLOSE,
            color=THEME.text_secondary,
            on_click=self._collapse,
            tooltip="收起",
            size=16,
        )
        header_content = ft.Row(
            [
                ft.Icon(
                    ft.Icons.ARTICLE_OUTLINED,
                    size=16,
                    color=THEME.mc_gold,
                ),
                ft.Text(
                    title,
                    size=12,
                    color=THEME.mc_gold,
                    weight=ft.FontWeight.BOLD,
                ),
                self._status_text,
                ft.Container(expand=True),
                self._auto_scroll_btn,
                self._clear_btn,
                self._close_btn,
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        header = ft.Container(
            content=header_content,
            height=38,
            padding=ft.Padding(left=12, right=8, top=4, bottom=4),
            bgcolor=THEME.mc_coal,
            border_radius=ft.BorderRadius(
                top_left=8,
                top_right=8,
                bottom_left=0,
                bottom_right=0,
            ),
        )
        self._header_detector = ft.GestureDetector(
            content=header,
            on_pan_start=self._on_pan_start,
            on_pan_update=self._on_pan_update,
            on_pan_end=self._on_pan_end,
        )

    @staticmethod
    def _header_icon_button(
        *,
        icon: Any,
        color: str,
        on_click: Callable[..., Any],
        tooltip: str,
        size: int = 14,
    ) -> ft.Container:
        return ft.Container(
            content=ft.Icon(icon, size=size, color=color),
            on_click=on_click,
            padding=4,
            border_radius=4,
            tooltip=tooltip,
        )

    def _load_position(self) -> None:
        """从共享偏好加载保存的位置。"""
        self._position_store.load(self._apply_position)

    def _apply_position(self, left: float, top: float) -> None:
        self._offset_left = left
        self._offset_top = top
        self.left = left
        self.top = top

    def _save_position(self) -> None:
        """保存位置到共享偏好。"""
        self._position_store.save(self._offset_left, self._offset_top)

    def _scroll_to_end(self) -> None:
        try:
            self._page.run_task(self._log_col.scroll_to, offset=-1)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        """开始拖拽"""
        try:
            self._drag.start(e.local_position.x, e.local_position.y)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        """拖拽更新"""
        try:
            delta = self._drag.update(
                e.local_position.x,
                e.local_position.y,
            )
            if delta is not None:
                bounds = FloatingBounds(
                    viewport_width=float(self._page.width or 1024),
                    viewport_height=float(self._page.height or 768),
                    control_width=float(self.width or self.DEFAULT_WIDTH),
                    control_height=float(self.height or self.DEFAULT_HEIGHT),
                )
                left, top = clamp_position(
                    self._offset_left + delta[0],
                    self._offset_top + delta[1],
                    bounds,
                )
                self._apply_position(left, top)
                self.update()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _on_pan_end(self, e: ft.DragEndEvent) -> None:
        """拖拽结束"""
        try:
            self._drag.end()
            self._save_position()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _on_scroll(self, e: ft.OnScrollEvent) -> None:
        """滚动事件 - 暂停自动滚动"""
        try:
            # 用户手动滚动时暂停自动滚动
            if e.event_type == "scroll":
                self._auto_scroll = False
                self._auto_scroll_btn.content = ft.Icon(
                    ft.Icons.VERTICAL_ALIGN_BOTTOM,
                    size=14,
                    color=THEME.text_muted,
                )
                self._auto_scroll_btn.tooltip = "已暂停自动滚动"
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self._auto_scroll_btn)

    def _toggle_auto_scroll(self) -> None:
        """切换自动滚动"""
        try:
            self._auto_scroll = not self._auto_scroll
            self._auto_scroll_btn.content = ft.Icon(
                ft.Icons.VERTICAL_ALIGN_BOTTOM,
                size=14,
                color=(
                    THEME.terminal_green
                    if self._auto_scroll
                    else THEME.text_muted
                ),
            )
            self._auto_scroll_btn.tooltip = (
                "自动滚动" if self._auto_scroll else "已暂停自动滚动"
            )
            if self._auto_scroll and self._log_col.controls:
                self._scroll_to_end()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self._auto_scroll_btn)
        safe_update(self)

    def _expand(self) -> None:
        """展开面板"""
        try:
            self.visible = True
            self._expanded = True
            self._flush_pending_ui(refresh=False)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self)

    def _collapse(self) -> None:
        """收起面板"""
        try:
            # Mark hidden before touching the timer so a queued UI callback
            # observes the hidden state and leaves pending messages queued.
            self.visible = False
            # 清理定时器
            with self._log_lock:
                timer = self._flush_timer
                self._flush_timer = None
                self._log_flush_scheduled = False
                self._flush_generation += 1
            if timer is not None:
                timer.cancel()

            self._expanded = False
            self._save_position()
            self._page.update()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _clear(self) -> None:
        """清除日志"""
        try:
            with self._log_lock:
                self._pending_logs.clear()
            self._log_col.controls.clear()
            self._status_text.value = ""
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self)

    def log(self, message: str, level: str = "info") -> None:
        """添加日志消息（批量刷新，避免每行触发 UI 更新）"""
        # 关闭时跳过日志更新
        if _is_app_closing():
            return

        should_schedule = False
        with self._log_lock:
            self._pending_logs.append((message, level))
            if self.visible and not self._log_flush_scheduled:
                self._log_flush_scheduled = True
                should_schedule = True
        if should_schedule:
            self._schedule_flush()

    def _schedule_flush(self) -> None:
        """延迟刷新 UI，避免频繁更新"""
        with self._log_lock:
            if (
                self._flush_timer is not None
                or not self.visible
                or not self._log_flush_scheduled
            ):
                return
            self._flush_generation += 1
            generation = self._flush_generation

            def _flush() -> None:
                run_on_ui(
                    self._page,
                    self._flush_pending_ui,
                    generation=generation,
                )

            timer = threading.Timer(0.3, _flush)
            timer.daemon = True
            self._flush_timer = timer
        timer.start()

    def _flush_pending_ui(
        self,
        *,
        refresh: bool = True,
        generation: int | None = None,
    ) -> None:
        """Create controls for a pending batch on the UI event loop."""
        with self._log_lock:
            if generation is not None and generation != self._flush_generation:
                return
            if not self.visible:
                # The timer can race with collapse/set_visible(False).  Do not
                # allocate Flet controls for a hidden panel; the next expand
                # will drain this plain-text queue on the UI thread.
                self._flush_timer = None
                self._log_flush_scheduled = False
                return
            batch = list(self._pending_logs)
            self._pending_logs.clear()
            self._flush_timer = None
            self._log_flush_scheduled = False
        if not batch:
            return

        color_map = {
            "info": THEME.text_primary,
            "success": THEME.terminal_green,
            "warn": THEME.terminal_yellow,
            "error": THEME.terminal_red,
            "api": THEME.terminal_blue,
            "timestamp": THEME.text_muted,
            "header": THEME.accent,
            "separator": THEME.border_standard,
        }
        self._log_col.controls.extend(
            ft.Text(
                message,
                color=color_map.get(level, THEME.text_primary),
                size=11,
                font_family="monospace",
            )
            for message, level in batch
        )
        del self._log_col.controls[:-self.MAX_LINES]
        self._status_text.value = f"({len(self._log_col.controls)})"
        if refresh and self.visible:
            self.update()
            if self._auto_scroll:
                self._scroll_to_end()

    def set_visible(self, visible: bool) -> None:
        """设置可见性"""
        try:
            timer = None
            if not visible:
                self.visible = False
                with self._log_lock:
                    timer = self._flush_timer
                    self._flush_timer = None
                    self._log_flush_scheduled = False
                    self._flush_generation += 1
                if timer is not None:
                    timer.cancel()
            else:
                self.visible = True
            if visible:
                self._expanded = True
                self._flush_pending_ui(refresh=False)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self._page)

    @property
    def is_visible(self) -> bool:
        """是否可见"""
        return self.visible


class FloatingLogButton(ft.Container):
    """悬浮球按钮 - 点击展开/收起日志面板，支持拖拽移动"""

    def __init__(
            self,
            floating_panel: FloatingLogPanel,
            page: ft.Page,
            on_click=None) -> None:
        self._floating_panel = floating_panel
        self._on_click_handler = on_click
        self._page = page
        self._offset_right = 20.0
        self._offset_bottom = 20.0
        self._storage_key = "floating_log_button_position"
        self._drag = DragTracker()
        self._position_store = SharedPositionStore(page, self._storage_key)

        # 按钮容器 — Material Icon 代替 emoji
        self._button = ft.Container(
            content=ft.Icon(IconSet.DOCUMENT, size=22, color=THEME.mc_gold),
            width=48,
            height=48,
            bgcolor=THEME.mc_coal,
            border_radius=24,
            alignment=ft.alignment.Alignment(0, 0),
            tooltip="日志面板",
            shadow=mc_shadow(2),
            border=mc_border(),
        )

        # 拖拽检测器
        self._gesture_detector = ft.GestureDetector(
            content=self._button,
            on_pan_start=self._on_pan_start,
            on_pan_update=self._on_pan_update,
            on_pan_end=self._on_pan_end,
            on_tap=self._click,
        )

        super().__init__(
            content=self._gesture_detector,
            width=48,
            height=48,
            right=self._offset_right,
            bottom=self._offset_bottom,
        )
        self._load_position()

    def _load_position(self) -> None:
        """加载保存的位置"""
        self._position_store.load(self._apply_position)

    def _apply_position(self, right: float, bottom: float) -> None:
        self._offset_right = right
        self._offset_bottom = bottom
        self.right = right
        self.bottom = bottom

    def _save_position(self) -> None:
        """保存位置"""
        self._position_store.save(self._offset_right, self._offset_bottom)

    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        """开始拖拽"""
        try:
            self._drag.start(e.local_position.x, e.local_position.y)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        """拖拽更新"""
        try:
            delta = self._drag.update(
                e.local_position.x,
                e.local_position.y,
            )
            if delta is not None:
                bounds = FloatingBounds(
                    viewport_width=float(self._page.width or 1024),
                    viewport_height=float(self._page.height or 768),
                    control_width=48,
                    control_height=48,
                )
                right, bottom = clamp_position(
                    self._offset_right - delta[0],
                    self._offset_bottom - delta[1],
                    bounds,
                )
                self._apply_position(right, bottom)
                self.update()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _on_pan_end(self, e: ft.DragEndEvent) -> None:
        """拖拽结束"""
        try:
            self._drag.end()
            self._save_position()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _click(self) -> None:
        """点击事件 - 如果不是拖拽就触发点击"""
        if self._drag.active:
            return  # 正在拖拽，不触发点击
        try:
            if self._floating_panel.is_visible:
                self._floating_panel.set_visible(False)
                self._button.content = ft.Icon(
                    IconSet.DOCUMENT, size=22, color=THEME.mc_gold)
            else:
                self._floating_panel.set_visible(True)
                self._button.content = ft.Icon(
                    IconSet.CLOSE, size=20, color=THEME.mc_redstone)
            self._button.update()
            if self._on_click_handler:
                self._on_click_handler()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def set_visible(self, visible: bool) -> None:
        """设置可见性"""
        try:
            self.visible = visible
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self)

    def update_icon(self, expanded: bool) -> None:
        """更新图标"""
        try:
            if expanded:
                self._button.content = ft.Icon(
                    IconSet.CLOSE, size=20, color=THEME.mc_redstone)
            else:
                self._button.content = ft.Icon(
                    IconSet.DOCUMENT, size=22, color=THEME.mc_gold)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self._button)

"""Progress Manager - 进度管理

负责进度条的显示、隐藏、更新和标签设置。
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable, Optional
import flet as ft

from app.ui.theme import THEME
from app.ui.utils import run_on_ui

TranslateCallback = Callable[..., str]

if TYPE_CHECKING:
    from app.ui.components.progress import McProgressBar


class ProgressManager:
    """进度管理器

    职责：
    - 进度条显示和隐藏
    - 进度值更新
    - 进度标签设置
    - 进度条容器管理
    """

    def __init__(self, page: ft.Page, translate: TranslateCallback) -> None:
        self.page = page
        self._translate = translate
        self._progress_bar: Optional[McProgressBar] = None
        self._progress_label: Optional[ft.Text] = None
        self._progress_container: Optional[ft.Container] = None
        self._progress_lock = threading.Lock()
        self._last_progress_key: Optional[tuple[str, int]] = None
        self._desired_visible = False
        self._desired_value = 0.0
        self._desired_label = ""

    def create_progress_ui(self) -> ft.Container:
        """创建进度条UI组件

        Returns:
            ft.Container: 进度条容器
        """
        from app.ui.components.progress import McProgressBar

        self._progress_bar = McProgressBar(
            value=0.0,
            color=THEME.mc_diamond,
            height=8,
            show_percentage=False,
            animated=True,
        )

        self._progress_label = ft.Text(
            self._translate("top_bar.ready", "就绪"),
            size=12,
            color=THEME.mc_gold,
            weight=ft.FontWeight.BOLD,
            font_family="monospace",
        )
        with self._progress_lock:
            self._desired_visible = False
            self._desired_value = 0.0
            self._desired_label = self._progress_label.value or "就绪"

        # 进度条容器（默认隐藏）
        self._progress_container = ft.Container(
            content=ft.Row(
                [self._progress_label, self._progress_bar],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,
        )

        return self._progress_container

    def _update_ui_safe(self, update_func: Callable[[], None]) -> None:
        """安全地更新 UI（线程安全）

        Args:
            update_func: 更新函数
        """
        try:
            run_on_ui(self.page, update_func)
        except Exception:
            # 如果 run_on_ui 失败，尝试直接更新
            try:
                update_func()
            except Exception:
                pass

    def _apply_desired_state(self) -> None:
        """Apply the latest aggregate state, regardless of callback order."""
        container = self._progress_container
        progress_bar = self._progress_bar
        progress_label = self._progress_label
        if container is None or progress_bar is None or progress_label is None:
            return
        with self._progress_lock:
            visible = self._desired_visible
            value = self._desired_value
            label = self._desired_label
        container.visible = visible
        progress_bar.set_value(value, refresh=False)
        progress_label.value = label
        self._refresh_container(container)

    def update_progress(self, value: float) -> None:
        """更新进度条

        Args:
            value: 进度值（0.0 到 1.0）
        """
        container = self._progress_container
        progress_bar = self._progress_bar
        progress_label = self._progress_label
        if container is None or progress_bar is None or progress_label is None:
            return
        percent = max(0, min(100, int(value * 100)))
        with self._progress_lock:
            key = ("", percent)
            if key == self._last_progress_key:
                return
            self._last_progress_key = key
            self._desired_visible = True
            self._desired_value = value
            self._desired_label = self._translate(
                "top_bar.progress",
                "进度 {percent}%",
                percent=percent,
            )

        def _update() -> None:
            self._apply_desired_state()

        self._update_ui_safe(_update)

    def show_progress(self, task_name: str = "") -> None:
        """显示进度条

        Args:
            task_name: 任务名称（如"转换中"、"扫描中"等）
        """
        container = self._progress_container
        progress_bar = self._progress_bar
        progress_label = self._progress_label
        if container is None or progress_bar is None or progress_label is None:
            return
        with self._progress_lock:
            self._last_progress_key = None
            self._desired_visible = True
            self._desired_value = 0.0
            self._desired_label = task_name or "处理中..."

        def _update() -> None:
            self._apply_desired_state()

        self._update_ui_safe(_update)

    def hide_progress(self) -> None:
        """隐藏进度条"""
        container = self._progress_container
        progress_bar = self._progress_bar
        progress_label = self._progress_label
        if container is None or progress_bar is None or progress_label is None:
            return
        with self._progress_lock:
            self._last_progress_key = None
            self._desired_visible = False
            self._desired_value = 0.0
            self._desired_label = self._translate("top_bar.ready", "就绪")

        def _update() -> None:
            self._apply_desired_state()

        self._update_ui_safe(_update)

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """更新进度条（带任务名称）

        Args:
            task_name: 任务名称
            value: 进度值（0.0 到 1.0）
        """
        container = self._progress_container
        progress_bar = self._progress_bar
        progress_label = self._progress_label
        if container is None or progress_bar is None or progress_label is None:
            return
        percent = max(0, min(100, int(value * 100)))
        with self._progress_lock:
            key = (task_name, percent)
            if key == self._last_progress_key:
                return
            self._last_progress_key = key
            self._desired_visible = True
            self._desired_value = value
            self._desired_label = (
                f"{task_name} {int(value * 100)}%"
                if 0 <= value <= 1.0
                else task_name
            )

        def _update() -> None:
            self._apply_desired_state()

        self._update_ui_safe(_update)

    def set_progress_label(self, text: str) -> None:
        """设置进度标签文本

        Args:
            text: 标签文本
        """
        container = self._progress_container
        progress_label = self._progress_label
        if container is None or progress_label is None:
            return
        with self._progress_lock:
            self._last_progress_key = None
            self._desired_visible = True
            self._desired_label = text

        def _update() -> None:
            self._apply_desired_state()

        self._update_ui_safe(_update)

    def set_progress_value(self, value: float) -> None:
        """设置进度条值

        Args:
            value: 进度值 (0.0 - 1.0)
        """
        progress_bar = self._progress_bar
        if progress_bar is None:
            return
        with self._progress_lock:
            self._last_progress_key = None
            self._desired_value = value

        def _update() -> None:
            self._apply_desired_state()

        self._update_ui_safe(_update)

    def _refresh_container(self, control: ft.Control) -> None:
        """Refresh only the progress subtree; fake/unmounted pages use fallback."""
        try:
            control.update()
        except (RuntimeError, AttributeError):
            self.page.update()

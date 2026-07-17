"""Progress Manager - 进度管理

负责进度条的显示、隐藏、更新和标签设置。
"""
from __future__ import annotations

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

        def _update() -> None:
            # 确保进度条可见
            if not container.visible:
                container.visible = True

            # 更新进度值和标签
            progress_bar.set_value(value)
            progress_label.value = self._translate(
                "top_bar.progress",
                "进度 {percent}%",
                percent=int(value * 100),
            )
            self.page.update()

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

        def _update() -> None:
            container.visible = True

            if task_name:
                progress_label.value = task_name
            else:
                progress_label.value = "处理中..."

            progress_bar.set_value(0.0)
            self.page.update()

        self._update_ui_safe(_update)

    def hide_progress(self) -> None:
        """隐藏进度条"""
        container = self._progress_container
        progress_bar = self._progress_bar
        progress_label = self._progress_label
        if container is None or progress_bar is None or progress_label is None:
            return

        def _update() -> None:
            container.visible = False
            progress_label.value = self._translate("top_bar.ready", "就绪")
            progress_bar.set_value(0.0)
            self.page.update()

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

        def _update() -> None:
            # 确保进度条可见
            if not container.visible:
                container.visible = True

            # 设置任务名称和进度
            if value >= 0 and value <= 1.0:
                progress_label.value = f"{task_name} {int(value * 100)}%"
            else:
                progress_label.value = task_name

            progress_bar.set_value(value)
            self.page.update()

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

        def _update() -> None:
            # 确保进度条可见
            if not container.visible:
                container.visible = True

            progress_label.value = text
            self.page.update()

        self._update_ui_safe(_update)

    def set_progress_value(self, value: float) -> None:
        """设置进度条值

        Args:
            value: 进度值 (0.0 - 1.0)
        """
        progress_bar = self._progress_bar
        if progress_bar is None:
            return

        def _update() -> None:
            progress_bar.set_value(value)
            self.page.update()

        self._update_ui_safe(_update)

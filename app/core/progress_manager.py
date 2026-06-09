"""Progress Manager - 进度管理

负责进度条的显示、隐藏、更新和标签设置。
"""
from typing import TYPE_CHECKING
import flet as ft

from app.ui.theme import THEME

if TYPE_CHECKING:
    from app.application import Application


class ProgressManager:
    """进度管理器

    职责：
    - 进度条显示和隐藏
    - 进度值更新
    - 进度标签设置
    - 进度条容器管理
    """

    def __init__(self, app: "Application") -> None:
        """初始化进度管理器

        Args:
            app: 应用实例
        """
        self.app = app
        self.page = app.page
        self._progress_bar = None
        self._progress_label = None
        self._progress_container = None

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
            self.app._t("top_bar.ready", "就绪"),
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

    def update_progress(self, value: float) -> None:
        """更新进度条

        Args:
            value: 进度值（0.0 到 1.0）
        """
        if not self._progress_container or not self._progress_bar:
            return

        # 确保进度条可见
        if not self._progress_container.visible:
            self._progress_container.visible = True

        # 更新进度值和标签
        self._progress_bar.set_value(value)
        self._progress_label.value = self.app._t(
            "top_bar.progress",
            "进度 {percent}%",
            percent=int(value * 100),
        )
        self.page.update()

    def show_progress(self, task_name: str = "") -> None:
        """显示进度条

        Args:
            task_name: 任务名称（如"转换中"、"扫描中"等）
        """
        if not self._progress_container or not self._progress_bar:
            return

        self._progress_container.visible = True

        if task_name:
            self._progress_label.value = task_name
        else:
            self._progress_label.value = "处理中..."

        self._progress_bar.set_value(0.0)
        self.page.update()

    def hide_progress(self) -> None:
        """隐藏进度条"""
        if not self._progress_container or not self._progress_bar:
            return

        self._progress_container.visible = False
        self._progress_label.value = self.app._t("top_bar.ready", "就绪")
        self._progress_bar.set_value(0.0)
        self.page.update()

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """更新进度条（带任务名称）

        Args:
            task_name: 任务名称
            value: 进度值（0.0 到 1.0）
        """
        if not self._progress_container or not self._progress_bar:
            return

        # 确保进度条可见
        if not self._progress_container.visible:
            self._progress_container.visible = True

        # 设置任务名称和进度
        if value >= 0 and value <= 1.0:
            self._progress_label.value = f"{task_name} {int(value * 100)}%"
        else:
            self._progress_label.value = task_name

        self._progress_bar.set_value(value)
        self.page.update()

    def set_progress_label(self, text: str) -> None:
        """设置进度标签文本

        Args:
            text: 标签文本
        """
        if not self._progress_container or not self._progress_label:
            return

        # 确保进度条可见
        if not self._progress_container.visible:
            self._progress_container.visible = True

        self._progress_label.value = text
        self.page.update()

    def set_progress_value(self, value: float) -> None:
        """设置进度条值

        Args:
            value: 进度值 (0.0 - 1.0)
        """
        if not self._progress_bar:
            return

        self._progress_bar.set_value(value)

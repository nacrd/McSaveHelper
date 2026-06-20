"""布局优化组件 - 降低信息密度感

提供以下优化组件：
1. 可折叠区域
2. 增强的卡片
3. 分组容器
4. 引导提示
"""
import flet as ft
from typing import Optional, List, Callable

from app.ui.theme import THEME, mc_border
from app.ui.icons import IconSet


class CollapsibleSection(ft.Container):
    """可折叠区域组件

    用于将次要信息折叠起来，减少视觉压力。
    用户可以点击标题展开/折叠内容。
    """

    def __init__(
        self,
        title: str,
        content: ft.Control,
        icon: str = "",
        initially_expanded: bool = False,
        help_text: Optional[str] = None,
    ) -> None:
        self._title = title
        self._icon = icon
        self._content = content
        self._expanded = initially_expanded
        self._help_text = help_text

        # 标题行
        self._title_row = ft.Row(
            [
                ft.Text(
                    f"{icon} {title}" if icon else title,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=THEME.text_primary,
                ),
                ft.Container(expand=True),
                ft.Icon(
                    ft.Icons.KEYBOARD_ARROW_DOWN if initially_expanded else ft.Icons.KEYBOARD_ARROW_RIGHT,
                    size=20,
                    color=THEME.text_muted,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # 内容区域
        self._content_container = ft.Container(
            content=content,
            visible=initially_expanded,
            animate_opacity=300,
        )

        # 帮助文本
        self._help_container = ft.Container(
            content=ft.Text(
                help_text,
                size=11,
                color=THEME.text_muted,
            ) if help_text else None,
            visible=initially_expanded and help_text is not None,
            padding=ft.Padding(left=0, right=0, top=8, bottom=0),
        )

        # 组合
        super().__init__(
            content=ft.Column(
                [
                    self._title_row,
                    self._content_container,
                    self._help_container,
                ],
                spacing=0,
            ),
            padding=12,
            bgcolor=THEME.bg_secondary,
            border_radius=8,
            border=ft.border.all(1, THEME.border_subtle),
            on_click=self._toggle,
            ink=True,
        )

    def _toggle(self, e: ft.ControlEvent) -> None:
        """切换展开/折叠状态"""
        self._expanded = not self._expanded
        self._content_container.visible = self._expanded
        self._help_container.visible = self._expanded and self._help_text is not None

        # 更新箭头图标
        arrow = self._title_row.controls[-1]
        if isinstance(arrow, ft.Icon):
            arrow.name = ft.Icons.KEYBOARD_ARROW_DOWN if self._expanded else ft.Icons.KEYBOARD_ARROW_RIGHT

        self.update()

    @property
    def expanded(self) -> bool:
        return self._expanded

    @expanded.setter
    def expanded(self, value: bool) -> None:
        self._expanded = value
        self._content_container.visible = value
        self._help_container.visible = value and self._help_text is not None
        arrow = self._title_row.controls[-1]
        if isinstance(arrow, ft.Icon):
            arrow.name = ft.Icons.KEYBOARD_ARROW_DOWN if value else ft.Icons.KEYBOARD_ARROW_RIGHT


class EnhancedCard(ft.Container):
    """增强的卡片组件

    提供更好的视觉层次和呼吸空间。
    """

    def __init__(
        self,
        title: str,
        content: ft.Control,
        icon: str = "",
        description: Optional[str] = None,
        padding: int = 20,
    ) -> None:
        # 标题行
        title_row = ft.Row(
            [
                ft.Text(
                    f"{icon} {title}" if icon else title,
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # 描述文本
        description_container = ft.Container(
            content=ft.Text(
                description,
                size=12,
                color=THEME.text_muted,
            ) if description else None,
            padding=ft.Padding(left=0, right=0, top=4, bottom=12),
        )

        # 内容区域
        content_container = ft.Container(
            content=content,
            padding=ft.Padding(left=0, right=0, top=0, bottom=0),
        )

        super().__init__(
            content=ft.Column(
                [
                    title_row,
                    description_container,
                    content_container,
                ],
                spacing=0,
            ),
            bgcolor=THEME.bg_card,
            border_radius=8,
            border=mc_border(2),
            padding=padding,
        )


class GroupContainer(ft.Container):
    """分组容器组件

    将相关的控件分组显示，增加视觉分隔。
    """

    def __init__(
        self,
        title: str,
        controls: List[ft.Control],
        icon: str = "",
        spacing: int = 12,
        padding: int = 16,
    ) -> None:
        # 标题
        title_row = ft.Row(
            [
                ft.Text(
                    f"{icon} {title}" if icon else title,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=THEME.text_primary,
                ),
            ]
        )

        # 控件列表
        controls_column = ft.Column(
            controls,
            spacing=spacing,
        )

        super().__init__(
            content=ft.Column(
                [
                    title_row,
                    ft.Container(height=8),  # 间距
                    controls_column,
                ],
                spacing=0,
            ),
            bgcolor=THEME.bg_secondary,
            border_radius=8,
            padding=padding,
        )


class GuideCard(ft.Container):
    """引导提示卡片

    提供操作引导和帮助信息。
    """

    def __init__(
        self,
        title: str,
        steps: List[str],
        icon: str = "📖",
        tips: Optional[List[str]] = None,
    ) -> None:
        # 标题
        title_row = ft.Row(
            [
                ft.Text(
                    f"{icon} {title}",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
            ]
        )

        # 步骤列表
        steps_column = ft.Column(
            [ft.Text(step, size=12, color=THEME.text_secondary) for step in steps],
            spacing=4,
        )

        # 提示信息
        tips_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text("💡 提示：", size=12, weight=ft.FontWeight.W_600,
                            color=THEME.text_secondary),
                    *[ft.Text(tip, size=11, color=THEME.text_muted) for tip in (tips or [])],
                ],
                spacing=4,
            ) if tips else None,
            padding=ft.Padding(left=0, right=0, top=12, bottom=0),
        )

        super().__init__(
            content=ft.Column(
                [
                    title_row,
                    ft.Container(height=8),
                    steps_column,
                    tips_container,
                ],
                spacing=0,
            ),
            bgcolor=THEME.bg_secondary,
            border_radius=8,
            border=ft.border.all(1, THEME.border_subtle),
            padding=16,
        )


class StatusCard(ft.Container):
    """状态显示卡片

    用于显示操作状态和进度。
    """

    def __init__(
        self,
        title: str,
        status: str = "未开始",
        progress: Optional[float] = None,
        icon: str = "📊",
    ) -> None:
        self._status_text = ft.Text(
            status,
            size=13,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary,
        )

        self._progress_bar = ft.ProgressBar(
            value=progress,
            visible=progress is not None,
            width=200,
        )

        super().__init__(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                f"{icon} {title}",
                                size=13,
                                weight=ft.FontWeight.W_600,
                                color=THEME.text_primary,
                            ),
                            ft.Container(expand=True),
                            self._status_text,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=8),
                    self._progress_bar,
                ],
                spacing=0,
            ),
            bgcolor=THEME.bg_secondary,
            border_radius=8,
            padding=16,
        )

    def update_status(self, status: str, progress: Optional[float] = None) -> None:
        """更新状态"""
        self._status_text.value = status
        if progress is not None:
            self._progress_bar.value = progress
            self._progress_bar.visible = True
        self.update()


class EmptyState(ft.Container):
    """空状态组件

    用于显示空状态时的引导信息。
    """

    def __init__(
        self,
        icon: str,
        title: str,
        description: str,
        action_text: Optional[str] = None,
        on_action: Optional[Callable] = None,
    ) -> None:
        # 图标
        icon_control = ft.Icon(
            icon,
            size=64,
            color=THEME.text_muted,
        )

        # 标题
        title_text = ft.Text(
            title,
            size=18,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_primary,
            text_align=ft.TextAlign.CENTER,
        )

        # 描述
        description_text = ft.Text(
            description,
            size=13,
            color=THEME.text_secondary,
            text_align=ft.TextAlign.CENTER,
        )

        # 操作按钮
        action_button = ft.Container(
            content=ft.ElevatedButton(
                text=action_text,
                on_click=on_action,
                style=ft.ButtonStyle(
                    bgcolor=THEME.mc_grass,
                    color=THEME.text_primary,
                ),
            ) if action_text and on_action else None,
            padding=ft.Padding(left=0, right=0, top=16, bottom=0),
        )

        super().__init__(
            content=ft.Column(
                [
                    icon_control,
                    ft.Container(height=16),
                    title_text,
                    ft.Container(height=8),
                    description_text,
                    action_button,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            padding=40,
            alignment=ft.alignment.Alignment(0, 0),
        )


def spaced_row(
    controls: List[ft.Control],
    spacing: int = 12,
    vertical_alignment: ft.CrossAxisAlignment = ft.CrossAxisAlignment.CENTER,
) -> ft.Row:
    """创建带间距的行"""
    return ft.Row(
        controls,
        spacing=spacing,
        vertical_alignment=vertical_alignment,
    )


def spaced_column(
    controls: List[ft.Control],
    spacing: int = 12,
) -> ft.Column:
    """创建带间距的列"""
    return ft.Column(
        controls,
        spacing=spacing,
    )


def section_divider() -> ft.Container:
    """创建分隔线"""
    return ft.Container(
        content=ft.Divider(height=1, color=THEME.border_subtle),
        padding=ft.Padding(left=0, right=0, top=8, bottom=8),
    )


def add_breathing_space(
    control: ft.Control,
    top: int = 0,
    bottom: int = 0,
    left: int = 0,
    right: int = 0,
) -> ft.Container:
    """添加呼吸空间"""
    return ft.Container(
        content=control,
        padding=ft.Padding(left=left, right=right, top=top, bottom=bottom),
    )

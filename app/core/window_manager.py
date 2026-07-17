"""Window Manager - 窗口生命周期管理

负责窗口的创建、最大化、最小化、关闭、大小调整和响应式布局。
"""
from dataclasses import dataclass
from typing import Optional, Callable, Any, Protocol
from pathlib import Path
import flet as ft

from app.ui.theme import THEME, mc_border, get_theme_manager
from core.logger import logger


class ResponsiveSidebar(Protocol):
    def set_collapsed(self, collapsed: bool) -> None:
        ...

    def set_width(self, width: int) -> None:
        ...


@dataclass(frozen=True)
class ResponsiveShellHost:
    sidebar: ResponsiveSidebar
    main_row: ft.Row
    shell: ft.Container
    scrollable_content: ft.Container
    content: ft.Container


@dataclass(frozen=True)
class WindowManagerDependencies:
    page: ft.Page
    translate: Callable[[str, str], str]
    apply_compact_layout: Callable[[bool], None]
    stop_gui_optimizer: Callable[[], None]
    dispose_views: Callable[[], None]


class WindowManager:
    """窗口生命周期管理器

    职责：
    - 窗口基本设置（标题、图标、大小）
    - 自定义标题栏构建
    - 窗口控制按钮（最小化、最大化、关闭）
    - 窗口大小调整和响应式布局
    - 窗口事件处理
    """

    def __init__(self, dependencies: WindowManagerDependencies) -> None:
        self._deps = dependencies
        self.page = dependencies.page
        self._shutdown_started = False
        self._resize_timer: Optional[Any] = None
        self._maximize_button: Optional[ft.Container] = None
        self._responsive_host: Optional[ResponsiveShellHost] = None

    def attach_responsive_host(self, host: ResponsiveShellHost) -> None:
        """Attach shell controls after Application has built its layout."""
        self._responsive_host = host

    def setup_window(self) -> None:
        """设置窗口基本属性"""
        page = self.page
        page.title = self._deps.translate(
            "app.title",
            "MCSaveHelper · 存档管理工具",
        )
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = THEME.bg_primary
        page.window.bgcolor = THEME.bg_primary
        page.window.frameless = False
        page.window.title_bar_hidden = True
        page.window.title_bar_buttons_hidden = True
        page.window.resizable = True
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.padding = 0
        page.window.width = 1100
        page.window.height = 820
        page.window.min_width = 800
        page.window.min_height = 600

        # 添加窗口大小变化监听
        try:
            page.on_resize = self._on_window_resize
        except Exception:
            logger.warning("on_resize 事件不可用，跳过窗口大小监听", module="WindowManager")

        # 设置图标
        icon_path = self._resolve_icon_path()
        if icon_path:
            page.window.icon = icon_path

        # 监听主题变化
        get_theme_manager().register_listener(self._on_theme_changed)

    def _on_theme_changed(self, mode: str) -> None:
        """主题切换时更新窗口颜色"""
        try:
            self.page.bgcolor = THEME.bg_primary
            self.page.window.bgcolor = THEME.bg_primary
            self.page.theme_mode = (
                ft.ThemeMode.LIGHT if mode == "light" else ft.ThemeMode.DARK
            )
        except Exception:
            pass

    def build_title_bar(self) -> ft.Container:
        """构建自定义窗口标题栏

        Returns:
            ft.Container: 标题栏容器
        """
        title_content = self._create_title_content()
        title_drag_area = self._create_title_drag_area(title_content)

        return ft.Container(
            content=ft.Row(
                [title_drag_area, self._build_window_controls()],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=44,
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
            bgcolor=THEME.mc_wood,
            border=ft.Border(
                bottom=ft.BorderSide(3, THEME.mc_grass),
            ),
        )

    def _create_title_content(self) -> ft.Row:
        """创建标题内容

        Returns:
            ft.Row: 标题内容行
        """
        return ft.Row(
            [
                ft.Container(
                    content=ft.Text("⛏", size=16, color=THEME.mc_gold),
                    width=32, height=28,
                    alignment=ft.alignment.Alignment(0, 0),
                    bgcolor=THEME.bg_secondary,
                    border=mc_border(2),
                ),
                ft.Text(
                    self._deps.translate(
                        "app.title_bar",
                        "MCSaveHelper ▣ Minecraft Save Toolkit",
                    ),
                    size=13, color=THEME.text_primary,
                    weight=ft.FontWeight.BOLD, font_family="monospace",
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _create_title_drag_area(self, content: ft.Control) -> ft.WindowDragArea:
        """创建可拖拽标题区域

        Args:
            content: 标题内容

        Returns:
            ft.WindowDragArea: 可拖拽区域
        """
        return ft.WindowDragArea(
            ft.GestureDetector(content=content, on_double_tap=self._toggle_maximize),
            maximizable=True, expand=True,
        )

    def _build_window_controls(self) -> ft.Row:
        """构建窗口控制按钮组

        Returns:
            ft.Row: 控制按钮行
        """
        self._maximize_button = self._create_window_button(
            "□", THEME.mc_stone, self._toggle_maximize
        )

        return ft.Row(
            [
                self._create_window_button("—", THEME.mc_stone, self._minimize),
                self._maximize_button,
                self._create_window_button("×", THEME.mc_redstone, self._close),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _create_window_button(
        self,
        text: str,
        bgcolor: str,
        on_click: Callable[..., Any],
    ) -> ft.Container:
        """创建窗口控制按钮

        Args:
            text: 按钮文本
            bgcolor: 背景颜色
            on_click: 点击回调

        Returns:
            ft.Container: 按钮容器
        """
        return ft.Container(
            content=ft.Text(
                text,
                size=14,
                color=THEME.text_primary,
                weight=ft.FontWeight.BOLD,
                font_family="monospace",
                text_align=ft.TextAlign.CENTER,
            ),
            width=32,
            height=28,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=bgcolor,
            border=mc_border(2),
            on_click=on_click,
            ink=True,
        )

    def _minimize(self, e: ft.ControlEvent) -> None:
        """最小化窗口

        Args:
            e: 控制事件
        """
        self.page.window.minimized = True
        self.page.window.update()

    def _toggle_maximize(self, e: Any = None) -> None:
        """切换最大化/还原窗口

        Args:
            e: 事件对象（可选）
        """
        try:
            if getattr(self.page.window, "minimized", False):
                self.page.window.minimized = False
            self.page.window.maximized = not bool(
                getattr(self.page.window, "maximized", False)
            )
            self.page.window.update()
            self._sync_maximize_button_state()
        except Exception as ex:
            logger.error(f"切换窗口最大化失败: {ex}", module="WindowManager")

    def _sync_maximize_button_state(self) -> None:
        """同步最大化按钮显示状态"""
        try:
            if not self._maximize_button or not isinstance(
                self._maximize_button.content, ft.Text
            ):
                return

            is_maximized = getattr(self.page.window, "maximized", False)
            self._maximize_button.content.value = "❐" if is_maximized else "□"
            self._maximize_button.tooltip = "还原" if is_maximized else "最大化"
            self._maximize_button.update()
        except Exception:
            pass

    def _close(self, e: ft.ControlEvent) -> None:
        """关闭窗口

        Args:
            e: 控制事件
        """
        self.shutdown()

    def _on_window_event(self, e) -> None:
        """处理系统窗口事件

        Args:
            e: 窗口事件
        """
        try:
            event_type = getattr(e, "type", None)
            if event_type == ft.WindowEventType.CLOSE or str(event_type).lower().endswith("close"):
                self.shutdown()
            elif str(event_type).lower().endswith(("maximize", "unmaximize", "restore", "resize")):
                self._sync_maximize_button_state()
        except Exception:
            pass

    def _on_window_resize(self, e) -> None:
        """窗口大小变化时的响应（带防抖）

        Args:
            e: 窗口大小变化事件
        """
        try:
            # 防抖：取消上次延迟更新
            if self._resize_timer is not None:
                self._resize_timer.cancel()

            import threading
            self._resize_timer = threading.Timer(0.15, self._apply_resize)
            self._resize_timer.daemon = True
            self._resize_timer.start()
        except Exception as ex:
            logger.error(f"窗口大小变化处理失败: {ex}", module="WindowManager")

    def _apply_resize(self) -> None:
        """实际执行窗口大小调整"""
        try:
            width = float(self.page.window.width or 1100)
            height = float(self.page.window.height or 820)

            self.apply_responsive_layout(width, height)

            self.page.update()

            logger.debug(
                f"窗口大小变化: {width}x{height}",
                module="WindowManager"
            )
        except Exception as ex:
            logger.error(f"窗口大小变化处理失败: {ex}", module="WindowManager")

    def apply_responsive_layout(self, width: float, height: float) -> None:
        """应用响应式布局

        Args:
            width: 窗口宽度
            height: 窗口高度
        """
        compact = width < 980
        roomy = width >= 1300

        self._adjust_sidebar_width(compact, roomy)
        self._adjust_spacing_and_padding(compact)
        self._adjust_top_actions(compact)

    def _adjust_sidebar_width(self, compact: bool, roomy: bool) -> None:
        """调整侧边栏宽度 / 折叠状态

        窗口 < 800px 时自动收窄侧边栏，
        >= 800px 时恢复用户设置的展开状态。

        Args:
            compact: 是否紧凑模式（窗口 < 980px）
            roomy: 是否宽松模式（窗口 >= 1300px）
        """
        host = self._responsive_host
        if host is None:
            return
        sidebar = host.sidebar
        # 极窄窗口：自动收窄
        if compact and (self.page.window.width or 0) < 800:
            sidebar.set_collapsed(True)
        else:
            sidebar.set_collapsed(False)
            sidebar.set_width(230 if roomy else 205)

    def _adjust_spacing_and_padding(self, compact: bool) -> None:
        """调整间距和内边距

        Args:
            compact: 是否紧凑模式
        """
        host = self._responsive_host
        if host is None:
            return
        host.main_row.spacing = 6 if compact else 12
        shell_padding = 6 if compact else 12
        shell_margin = 4 if compact else 12
        host.shell.padding = shell_padding
        host.shell.margin = ft.Margin(
            left=shell_margin,
            right=shell_margin,
            top=0,
            bottom=shell_margin,
        )
        host.scrollable_content.padding = 6 if compact else 14
        host.content.padding = 8 if compact else 18

    def _adjust_top_actions(self, compact: bool) -> None:
        """调整顶部操作按钮

        Args:
            compact: 是否紧凑模式
        """
        self._deps.apply_compact_layout(compact)

    def shutdown(self) -> None:
        """执行应用关闭流程"""
        if self._shutdown_started:
            return
        self._shutdown_started = True

        self._set_closing_flag()
        self._stop_gui_optimizer()
        self._dispose_views()
        self._shutdown_logger()
        self._destroy_window_async()
        self._schedule_force_exit()

    def _set_closing_flag(self) -> None:
        """设置关闭标记"""
        from app.ui.utils import set_app_closing
        set_app_closing(True)

    def _stop_gui_optimizer(self) -> None:
        """Stop monitoring and heartbeat resources through their owner."""
        try:
            self._deps.stop_gui_optimizer()
        except Exception:
            pass

    def _dispose_views(self) -> None:
        """Release resources held by cached views before closing the window."""
        try:
            self._deps.dispose_views()
        except Exception:
            pass

    def _shutdown_logger(self) -> None:
        """关闭日志"""
        try:
            from core.logger import logger
            logger.shutdown()
        except Exception:
            pass

    def _destroy_window_async(self) -> None:
        """异步销毁窗口"""
        try:
            async def _destroy_window():
                try:
                    self.page.window.prevent_close = False
                    await self.page.window.destroy()
                except Exception:
                    try:
                        await self.page.window.close()
                    except Exception:
                        pass

            self.page.run_task(_destroy_window)
        except Exception:
            pass

    def _schedule_force_exit(self) -> None:
        """调度强制退出（兜底）"""
        try:
            import os
            import threading

            def _force_exit() -> None:
                os._exit(0)

            timer = threading.Timer(2.0, _force_exit)
            timer.daemon = True
            timer.start()
        except Exception:
            pass

    @staticmethod
    def _resolve_icon_path() -> Optional[str]:
        """解析应用图标路径

        Returns:
            Optional[str]: 图标路径，找不到则返回None
        """
        import sys
        icon_name = "mcsavehelper_icon.ico"
        candidates = []

        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            candidates.append(Path(bundle_dir) / icon_name)
            candidates.append(Path(sys.executable).parent / icon_name)

        candidates.append(Path(__file__).parent.parent.parent / icon_name)

        for p in candidates:
            if p.exists():
                return str(p)

        return None

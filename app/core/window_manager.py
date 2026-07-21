"""Window Manager - 窗口生命周期管理

负责窗口的创建、最大化、最小化、关闭、大小调整和响应式布局。
"""
from dataclasses import dataclass
from typing import Optional, Callable, Any, Protocol
from pathlib import Path
import flet as ft

from app.models.responsive_layout import (
    ResponsiveLayout,
    resolve_responsive_layout,
)
from app.ui.icons import IconSet
from app.ui.theme import THEME, get_theme_manager
from app.ui.utils import run_on_ui
from core.logger import logger


class ResponsiveSidebar(Protocol):
    """侧边栏响应式协议：折叠与宽度由窗口管理器驱动。"""

    def set_collapsed(self, collapsed: bool) -> None:
        """设置是否折叠为图标栏。"""
        ...

    def set_width(self, width: int) -> None:
        """设置展开态侧边栏宽度（像素）。"""
        ...


@dataclass(frozen=True)
class ResponsiveShellHost:
    """应用壳层中供响应式布局调整的控件句柄集合。

    Attributes:
        sidebar: 可折叠侧边栏。
        main_row: 侧栏+内容的主行布局。
        shell: 外壳容器。
        scrollable_content: 可滚动内容区。
        content: 当前视图内容宿主。
    """

    sidebar: ResponsiveSidebar
    main_row: ft.Row
    shell: ft.Container
    scrollable_content: ft.Container
    content: ft.Container


@dataclass(frozen=True)
class WindowManagerDependencies:
    """WindowManager 显式依赖注入包。

    Attributes:
        page: Flet 页面。
        translate: 翻译函数 ``(key, default) -> str``。
        apply_responsive_layout: 将布局配置投影到当前视图。
        get_sidebar_mode: 获取用户设置的侧栏模式。
        stop_gui_optimizer: 关闭时停止 GUI 优化后台任务。
        dispose_views: 关闭时释放视图资源。
        dispose_file_dialogs: 关闭时销毁 Tk 文件对话框工作线程。
        shutdown_execution_runtime: 关闭应用级后台任务运行时。
        close_world_indexes: 关闭共享世界只读索引缓存。
    """

    page: ft.Page
    translate: Callable[[str, str], str]
    apply_responsive_layout: Callable[[ResponsiveLayout], None]
    get_sidebar_mode: Callable[[], str]
    stop_gui_optimizer: Callable[[], None]
    dispose_views: Callable[[], None]
    dispose_file_dialogs: Callable[[], None] = lambda: None
    shutdown_execution_runtime: Callable[[], None] = lambda: None
    close_world_indexes: Callable[[], None] = lambda: None


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
        """用注入依赖构造窗口管理器（不执行窗口配置）。

        Args:
            dependencies: 页面、翻译与关闭清理回调。
        """
        self._deps = dependencies
        self.page = dependencies.page
        self._shutdown_started = False
        self._resize_timer: Optional[Any] = None
        self._maximize_button: Optional[ft.Container] = None
        self._responsive_host: Optional[ResponsiveShellHost] = None
        self._viewport_size = (1100.0, 820.0)

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
            # Flet versions may not expose on_resize on all platforms.
            logger.warning(
                "on_resize 事件不可用，跳过窗口大小监听",
                module="WindowManager",
            )

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
            # Theme may update after page dispose; ignore.
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
            padding=ft.Padding(left=14, right=8, top=4, bottom=4),
            bgcolor=THEME.bg_secondary,
            border=ft.Border(
                bottom=ft.BorderSide(1, THEME.border_subtle),
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
                    width=8,
                    height=8,
                    alignment=ft.alignment.Alignment(0, 0),
                    bgcolor=THEME.accent,
                    border_radius=2,
                ),
                ft.Text(
                    self._deps.translate(
                        "app.title_bar",
                        "MCSaveHelper ▣ Minecraft Save Toolkit",
                    ),
                    size=12,
                    color=THEME.text_secondary,
                    weight=ft.FontWeight.W_500,
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
            IconSet.MAXIMIZE,
            self._toggle_maximize,
            "最大化",
        )

        return ft.Row(
            [
                self._create_window_button(
                    IconSet.MINIMIZE,
                    self._minimize,
                    "最小化",
                ),
                self._maximize_button,
                self._create_window_button(
                    IconSet.CLOSE,
                    self._close,
                    "关闭",
                    is_danger=True,
                ),
            ],
            spacing=2,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _create_window_button(
        self,
        icon: ft.IconData,
        on_click: Callable[..., Any],
        tooltip: str,
        is_danger: bool = False,
    ) -> ft.Container:
        """创建窗口控制按钮

        Args:
            icon: 按钮图标。
            on_click: 点击回调
            tooltip: 悬停提示。
            is_danger: 是否为关闭类危险操作。

        Returns:
            ft.Container: 按钮容器
        """
        return ft.Container(
            content=ft.Icon(
                icon,
                size=15,
                color=THEME.error if is_danger else THEME.text_secondary,
            ),
            width=44,
            height=44,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=ft.Colors.TRANSPARENT,
            border_radius=4,
            on_click=on_click,
            ink=True,
            tooltip=tooltip,
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
            logger.error(
                f"切换窗口最大化失败: {ex}",
                module="WindowManager",
            )

    def _sync_maximize_button_state(self) -> None:
        """同步最大化按钮显示状态"""
        try:
            if not self._maximize_button or not isinstance(
                self._maximize_button.content, ft.Icon
            ):
                return

            is_maximized = getattr(self.page.window, "maximized", False)
            self._maximize_button.content = ft.Icon(
                IconSet.RESTORE if is_maximized else IconSet.MAXIMIZE,
                size=15,
                color=THEME.text_secondary,
            )
            self._maximize_button.tooltip = "还原" if is_maximized else "最大化"
            self._maximize_button.update()
        except Exception:
            # Button may already be unmounted.
            pass

    def _close(self, e: ft.ControlEvent) -> None:
        """关闭窗口

        Args:
            e: 控制事件
        """
        self.shutdown()

    def _on_window_event(self, e: Any) -> None:
        """处理系统窗口事件

        Args:
            e: 窗口事件
        """
        try:
            event_type = getattr(e, "type", None)
            if (
                event_type == ft.WindowEventType.CLOSE
                or str(event_type).lower().endswith("close")
            ):
                self.shutdown()
            elif str(event_type).lower().endswith(
                ("maximize", "unmaximize", "restore", "resize")
            ):
                self._sync_maximize_button_state()
        except Exception:
            # Event plumbing is best-effort across Flet hosts.
            pass

    def _on_window_resize(self, e: Any) -> None:
        """窗口大小变化时的响应（带防抖）

        Args:
            e: 窗口大小变化事件
        """
        try:
            self._capture_viewport_size(e)
            # 防抖：取消上次延迟更新
            if self._resize_timer is not None:
                self._resize_timer.cancel()

            import threading
            self._resize_timer = threading.Timer(
                0.15,
                self._schedule_resize_apply,
            )
            self._resize_timer.daemon = True
            self._resize_timer.start()
        except Exception as ex:
            logger.error(
                f"窗口大小变化处理失败: {ex}",
                module="WindowManager",
            )

    def _capture_viewport_size(self, event: Any) -> None:
        """Capture event dimensions before the debounced callback runs."""
        window = self.page.window
        width = float(
            getattr(event, "width", 0.0)
            or window.width
            or self._viewport_size[0]
        )
        height = float(
            getattr(event, "height", 0.0)
            or window.height
            or self._viewport_size[1]
        )
        self._viewport_size = (width, height)

    def _schedule_resize_apply(self) -> None:
        """Schedule debounced layout work back onto the Flet UI thread."""
        run_on_ui(self.page, self._apply_resize)

    def _apply_resize(self) -> None:
        """在 UI 线程应用最新窗口尺寸。"""
        try:
            width, height = self._viewport_size

            self.apply_responsive_layout(width, height)

            self.page.update()

            logger.debug(
                f"窗口大小变化: {width}x{height}",
                module="WindowManager",
            )
        except Exception as ex:
            logger.error(
                f"窗口大小变化处理失败: {ex}",
                module="WindowManager",
            )

    def apply_responsive_layout(self, width: float, height: float) -> None:
        """应用响应式布局

        Args:
            width: 窗口宽度
            height: 窗口高度
        """
        self._viewport_size = (float(width), float(height))
        layout = resolve_responsive_layout(width, height)
        self._apply_shell_layout(layout)
        self._deps.apply_responsive_layout(layout)

    def refresh_responsive_layout(self) -> None:
        """Reapply layout for the current window dimensions and preferences."""
        width, height = self._read_page_viewport()
        self.apply_responsive_layout(width, height)

    def _read_page_viewport(self) -> tuple[float, float]:
        """Prefer the live page viewport, falling back to the last event size."""
        width = float(
            getattr(self.page, "width", 0.0)
            or self._viewport_size[0]
        )
        height = float(
            getattr(self.page, "height", 0.0)
            or self._viewport_size[1]
        )
        return width, height

    def _apply_shell_layout(self, layout: ResponsiveLayout) -> None:
        """将已解析的布局配置应用到壳层控件。

        Args:
            layout: 当前窗口对应的不可变响应式配置。
        """
        host = self._responsive_host
        if host is None:
            return
        host.sidebar.set_width(layout.sidebar_width)
        host.sidebar.set_collapsed(self._should_collapse_sidebar(layout))
        host.main_row.spacing = 0
        host.shell.padding = 0
        host.shell.margin = 0
        host.scrollable_content.padding = 0
        host.content.padding = layout.content_padding

    def _should_collapse_sidebar(self, layout: ResponsiveLayout) -> bool:
        """Combine viewport constraints with the user's sidebar preference."""
        if layout.sidebar_collapsed:
            return True
        return self._deps.get_sidebar_mode() == "collapsed"

    def shutdown(self) -> None:
        """执行应用关闭流程"""
        if self._shutdown_started:
            return
        self._shutdown_started = True

        self._set_closing_flag()
        self._stop_gui_optimizer()
        self._dispose_views()
        self._dispose_file_dialogs()
        self._shutdown_execution_runtime()
        self._close_world_indexes()
        self._shutdown_logger()
        self._destroy_window_async()

    def _set_closing_flag(self) -> None:
        """设置关闭标记"""
        from app.ui.utils import set_app_closing
        set_app_closing(True)

    def _stop_gui_optimizer(self) -> None:
        """Stop monitoring and heartbeat resources through their owner."""
        try:
            self._deps.stop_gui_optimizer()
        except Exception:
            # Shutdown must continue even if monitor teardown fails.
            pass

    def _dispose_views(self) -> None:
        """Release resources held by cached views before closing the window."""
        try:
            self._deps.dispose_views()
        except Exception:
            pass

    def _dispose_file_dialogs(self) -> None:
        """Destroy the platform file-dialog host on its owning thread."""
        try:
            self._deps.dispose_file_dialogs()
        except Exception:
            pass

    def _shutdown_execution_runtime(self) -> None:
        """取消并关闭应用持有的后台执行器。"""
        try:
            self._deps.shutdown_execution_runtime()
        except Exception:
            # 关闭流程必须继续执行，运行时清理失败只影响后台资源。
            pass

    def _close_world_indexes(self) -> None:
        """关闭应用作用域的世界索引缓存。"""
        try:
            self._deps.close_world_indexes()
        except Exception:
            pass

    def _shutdown_logger(self) -> None:
        """关闭日志"""
        try:
            from core.logger import logger as app_logger
            app_logger.shutdown()
        except Exception:
            pass

    def _destroy_window_async(self) -> None:
        """异步销毁窗口"""
        try:
            async def _destroy_window() -> None:
                try:
                    self.page.window.prevent_close = False
                    await self.page.window.destroy()
                except Exception:
                    try:
                        await self.page.window.close()
                    except Exception:
                        # Final close path is best-effort.
                        pass

            self.page.run_task(_destroy_window)
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

        for path in candidates:
            if path.exists():
                return str(path)

        return None

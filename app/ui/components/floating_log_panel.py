"""Floating log panel component — 可拖拽移动的悬浮球日志面板"""
import threading
import time
import flet as ft

from app.ui.theme import THEME, mc_border, mc_shadow
from app.ui.utils import run_on_ui


def _is_app_closing() -> bool:
    """检查应用是否正在关闭"""
    try:
        from app.ui.utils import is_app_closing
        return is_app_closing()
    except Exception:
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
    STORAGE_KEY = "floating_log_panel_position"

    def __init__(self, page: ft.Page, title: str = "日志") -> None:
        self._page = page
        self._title = title
        self._expanded = False
        self._auto_scroll = True
        self._is_dragging = False
        self._offset_left = 50.0
        self._offset_top = 200.0
        self._last_x = 0.0
        self._last_y = 0.0
        
        # 加载保存的位置
        self._load_position()
        
        # 创建日志列表（使用ListView以获得更好的滚动体验）
        self._log_col = ft.ListView(
            spacing=2,
            padding=0,
            expand=True,
            auto_scroll=True,
            on_scroll=self._on_scroll,
        )
        
        # 状态文本
        self._status_text = ft.Text(
            "",
            size=10,
            color=THEME.text_muted,
        )
        
        # 自动滚动开关
        self._auto_scroll_btn = ft.Container(
            content=ft.Icon(
                ft.Icons.VERTICAL_ALIGN_BOTTOM,
                size=14,
                color=THEME.terminal_green if self._auto_scroll else THEME.text_muted,
            ),
            on_click=self._toggle_auto_scroll,
            padding=4,
            border_radius=4,
            tooltip="自动滚动" if self._auto_scroll else "已暂停自动滚动",
        )
        
        # 清除按钮
        self._clear_btn = ft.Container(
            content=ft.Icon(ft.Icons.DELETE_OUTLINE, size=14, color=THEME.text_muted),
            on_click=self._clear,
            padding=4,
            border_radius=4,
            tooltip="清除日志",
        )
        
        # 关闭按钮
        self._close_btn = ft.Container(
            content=ft.Text("×", size=18, color=THEME.text_secondary),
            on_click=self._collapse,
            padding=4,
            border_radius=4,
            tooltip="收起",
        )
        
        # 标题栏（可拖拽）
        header_content = ft.Row(
            [
                ft.Text(f"📜 {title}", size=12, color=THEME.mc_gold, weight=ft.FontWeight.BOLD),
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
            height=36,
            padding=ft.Padding(left=10, right=6, top=4, bottom=4),
            bgcolor=THEME.mc_coal,
        )
        
        # 用手势检测器包装标题栏
        self._header_detector = ft.GestureDetector(
            content=header,
            on_pan_start=self._on_pan_start,
            on_pan_update=self._on_pan_update,
            on_pan_end=self._on_pan_end,
        )
        
        # 日志容器（带内边距）
        log_container = ft.Container(
            content=self._log_col,
            padding=ft.Padding(left=10, right=10, top=6, bottom=10),
            bgcolor=THEME.bg_primary,
            expand=True,
        )
        
        # 整体面板
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
            shadow=mc_shadow(6),
            visible=False,
            left=self._offset_left,
            top=self._offset_top,
        )

    def _load_position(self) -> None:
        """从 client_storage 加载保存的位置"""
        try:
            pos = self._page.client_storage.get(self.STORAGE_KEY)
            if pos:
                self._offset_left = pos.get("left", 50.0)
                self._offset_top = pos.get("top", 200.0)
        except Exception:
            pass

    def _save_position(self) -> None:
        """保存位置到 client_storage"""
        try:
            self._page.client_storage.set(self.STORAGE_KEY, {
                "left": self._offset_left,
                "top": self._offset_top,
            })
        except Exception:
            pass

    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        """开始拖拽"""
        try:
            self._is_dragging = True
            self._last_x = e.local_position.x
            self._last_y = e.local_position.y
        except Exception:
            pass

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        """拖拽更新"""
        try:
            if self._is_dragging:
                dx = e.local_position.x - self._last_x
                dy = e.local_position.y - self._last_y
                
                self._offset_left += dx
                self._offset_top += dy
                self._offset_left = max(0, min(self._page.width - self.width, self._offset_left))
                self._offset_top = max(0, min(self._page.height - self.height, self._offset_top))
                
                self.left = self._offset_left
                self.top = self._offset_top
                self.update()
                
                self._last_x = e.local_position.x
                self._last_y = e.local_position.y
        except Exception:
            pass

    def _on_pan_end(self, e: ft.DragEndEvent) -> None:
        """拖拽结束"""
        try:
            self._is_dragging = False
            self._save_position()
        except Exception:
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
                self._auto_scroll_btn.update()
        except Exception:
            pass

    def _toggle_auto_scroll(self, e: ft.ControlEvent = None) -> None:
        """切换自动滚动"""
        try:
            self._auto_scroll = not self._auto_scroll
            self._auto_scroll_btn.content = ft.Icon(
                ft.Icons.VERTICAL_ALIGN_BOTTOM,
                size=14,
                color=THEME.terminal_green if self._auto_scroll else THEME.text_muted,
            )
            self._auto_scroll_btn.tooltip = "自动滚动" if self._auto_scroll else "已暂停自动滚动"
            self._auto_scroll_btn.update()
            
            if self._auto_scroll and self._log_col.controls:
                self._log_col.scroll_to(index=-1)
                self.update()
        except Exception:
            pass

    def _expand(self, e: ft.ControlEvent = None) -> None:
        """展开面板"""
        try:
            self.visible = True
            self._expanded = True
            self.update()
        except Exception:
            pass

    def _collapse(self, e: ft.ControlEvent = None) -> None:
        """收起面板"""
        try:
            # 清理定时器
            if hasattr(self, '_flush_timer') and self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
            
            self.visible = False
            self._expanded = False
            self._save_position()
            self._page.update()
        except Exception:
            pass

    def _clear(self, e: ft.ControlEvent = None) -> None:
        """清除日志"""
        try:
            self._log_col.controls.clear()
            self._status_text.value = ""
            self._log_col.update()
            self._status_text.update()
        except Exception:
            pass

    def log(self, message: str, level: str = "info") -> None:
        """添加日志消息（批量刷新，避免每行触发 UI 更新）"""
        # 关闭时跳过日志更新
        if _is_app_closing():
            return
        
        try:
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
            self._log_col.controls.append(
                ft.Text(
                    message,
                    color=color_map.get(level, THEME.text_primary),
                    size=11,
                    font_family="monospace",
                )
            )
            # 限制日志行数
            max_lines = 300  # 进一步降低最大行数
            while len(self._log_col.controls) > max_lines:
                self._log_col.controls.pop(0)
            # 更新计数
            self._status_text.value = f"({len(self._log_col.controls)})"
            
            # 优化：使用单个定时器，避免创建多个 Timer
            if self.visible:
                now = time.monotonic()
                last = getattr(self, '_last_log_update', 0.0)
                
                if (now - last) >= 0.3:  # 增加更新间隔到 0.3 秒
                    self._last_log_update = now
                    self._schedule_flush()
                elif not hasattr(self, '_log_flush_scheduled') or not self._log_flush_scheduled:
                    self._log_flush_scheduled = True
                    self._schedule_flush()
        except Exception:
            pass
    
    def _schedule_flush(self) -> None:
        """延迟刷新 UI，避免频繁更新"""
        if not hasattr(self, '_flush_timer') or self._flush_timer is None:
            def _flush_ui():
                try:
                    if self.visible:
                        self.update()
                        if self._auto_scroll:
                            self._log_col.scroll_to(index=-1)
                except Exception:
                    pass
                self._log_flush_scheduled = False
                self._last_log_update = time.monotonic()
                self._flush_timer = None

            def _flush():
                run_on_ui(self._page, _flush_ui)
             
            self._flush_timer = threading.Timer(0.3, _flush)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def set_visible(self, visible: bool) -> None:
        """设置可见性"""
        try:
            self.visible = visible
            if visible:
                self._expanded = True
            self._page.update()
        except Exception:
            pass

    @property
    def is_visible(self) -> bool:
        """是否可见"""
        return self.visible


class FloatingLogButton(ft.Container):
    """悬浮球按钮 - 点击展开/收起日志面板，支持拖拽移动"""
    
    def __init__(self, floating_panel: FloatingLogPanel, page: ft.Page, on_click=None) -> None:
        self._floating_panel = floating_panel
        self._on_click_handler = on_click
        self._page = page
        self._is_dragging = False
        self._offset_right = 20.0
        self._offset_bottom = 20.0
        self._last_x = 0.0
        self._last_y = 0.0
        self._storage_key = "floating_log_button_position"
        
        # 加载保存的位置
        self._load_position()
        
        # 按钮容器
        self._button = ft.Container(
            content=ft.Text("📜", size=20),
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

    def _load_position(self) -> None:
        """加载保存的位置"""
        try:
            pos = self._page.client_storage.get(self._storage_key)
            if pos:
                self._offset_right = pos.get("right", 20.0)
                self._offset_bottom = pos.get("bottom", 20.0)
        except Exception:
            pass

    def _save_position(self) -> None:
        """保存位置"""
        try:
            self._page.client_storage.set(self._storage_key, {
                "right": self._offset_right,
                "bottom": self._offset_bottom,
            })
        except Exception:
            pass

    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        """开始拖拽"""
        try:
            self._is_dragging = True
            self._last_x = e.local_position.x
            self._last_y = e.local_position.y
        except Exception:
            pass

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        """拖拽更新"""
        try:
            if self._is_dragging:
                dx = e.local_position.x - self._last_x
                dy = e.local_position.y - self._last_y
                
                self._offset_right -= dx  # 修正左右方向
                self._offset_bottom -= dy
                self._offset_right = max(0, min(self._page.width - 48, self._offset_right))
                self._offset_bottom = max(0, min(self._page.height - 48, self._offset_bottom))
                
                self.right = self._offset_right
                self.bottom = self._offset_bottom
                self.update()
                
                self._last_x = e.local_position.x
                self._last_y = e.local_position.y
        except Exception:
            pass

    def _on_pan_end(self, e: ft.DragEndEvent) -> None:
        """拖拽结束"""
        try:
            self._is_dragging = False
            self._save_position()
        except Exception:
            pass

    def _click(self, e: ft.TapEvent = None) -> None:
        """点击事件 - 如果不是拖拽就触发点击"""
        if self._is_dragging:
            return  # 正在拖拽，不触发点击
        try:
            if self._floating_panel.is_visible:
                self._floating_panel.set_visible(False)
                self._button.content = ft.Text("📜", size=20)
            else:
                self._floating_panel.set_visible(True)
                self._button.content = ft.Text("×", size=18, color=THEME.mc_redstone)
            self._button.update()
            if self._on_click_handler:
                self._on_click_handler()
        except Exception:
            pass

    def set_visible(self, visible: bool) -> None:
        """设置可见性"""
        try:
            self.visible = visible
            self.update()
        except Exception:
            pass

    def update_icon(self, expanded: bool) -> None:
        """更新图标"""
        try:
            if expanded:
                self._button.content = ft.Text("×", size=18, color=THEME.mc_redstone)
            else:
                self._button.content = ft.Text("📜", size=20)
            self._button.update()
        except Exception:
            pass

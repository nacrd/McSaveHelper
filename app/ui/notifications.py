"""通知和反馈系统

提供统一的用户通知和反馈机制：
- 成功/错误/警告/信息提示
- Toast 通知
- 确认对话框
- 加载指示器
"""
from typing import Optional, Callable, List
from enum import Enum
import flet as ft
from app.ui.theme import THEME


def _is_closing() -> bool:
    """检查应用是否正在关闭"""
    try:
        from app.ui.utils import is_app_closing
        return is_app_closing()
    except Exception:
        return False


class NotificationType(Enum):
    """通知类型"""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class NotificationManager:
    """通知管理器"""
    
    def __init__(self, page: ft.Page):
        self.page = page
    
    def show_snackbar(
        self,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        duration_ms: int = 3000,
        action_label: Optional[str] = None,
        on_action: Optional[Callable] = None
    ) -> None:
        """显示 SnackBar 通知
        
        Args:
            message: 消息内容
            notification_type: 通知类型
            duration_ms: 显示时长（毫秒）
            action_label: 操作按钮标签
            on_action: 操作按钮回调
        """
        # 关闭时跳过通知
        if _is_closing():
            return
        
        # 根据类型选择颜色
        color_map = {
            NotificationType.SUCCESS: THEME.success,
            NotificationType.ERROR: THEME.error,
            NotificationType.WARNING: THEME.warning,
            NotificationType.INFO: THEME.info,
        }
        
        bgcolor = color_map.get(notification_type, THEME.info)
        
        # 创建操作按钮
        action = None
        if action_label and on_action:
            action = ft.SnackBarAction(
                action_label,
                on_click=on_action
            )
        
        # 显示 SnackBar
        try:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(message, color="white"),
                bgcolor=bgcolor,
                duration=duration_ms,
                action=action,
            )
            self.page.snack_bar.open = True
            self.page.update()
        except Exception:
            pass
    
    def show_success(self, message: str, duration_ms: int = 3000) -> None:
        """显示成功消息"""
        self.show_snackbar(message, NotificationType.SUCCESS, duration_ms)
    
    def show_error(self, message: str, duration_ms: int = 5000) -> None:
        """显示错误消息"""
        self.show_snackbar(message, NotificationType.ERROR, duration_ms)
    
    def show_warning(self, message: str, duration_ms: int = 4000) -> None:
        """显示警告消息"""
        self.show_snackbar(message, NotificationType.WARNING, duration_ms)
    
    def show_info(self, message: str, duration_ms: int = 3000) -> None:
        """显示信息消息"""
        self.show_snackbar(message, NotificationType.INFO, duration_ms)
    
    def show_confirmation(
        self,
        title: str,
        message: str,
        on_confirm: Callable,
        on_cancel: Optional[Callable] = None,
        confirm_text: str = "确认",
        cancel_text: str = "取消",
        destructive: bool = False
    ) -> None:
        """显示确认对话框
        
        Args:
            title: 对话框标题
            message: 确认消息
            on_confirm: 确认回调
            on_cancel: 取消回调
            confirm_text: 确认按钮文本
            cancel_text: 取消按钮文本
            destructive: 是否为危险操作（使用红色）
        """
        def handle_confirm(e):
            dialog.open = False
            self.page.update()
            on_confirm(e)
        
        def handle_cancel(e):
            dialog.open = False
            self.page.update()
            if on_cancel:
                on_cancel(e)
        
        # 确认按钮样式
        confirm_button = ft.ElevatedButton(
            confirm_text,
            on_click=handle_confirm,
            bgcolor=THEME.error if destructive else THEME.accent,
            color="white",
        )
        
        dialog = ft.AlertDialog(
            title=ft.Text(title, size=18, weight=ft.FontWeight.BOLD),
            content=ft.Text(message, size=14),
            actions=[
                ft.TextButton(cancel_text, on_click=handle_cancel),
                confirm_button,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
    
    def show_loading(
        self,
        title: str = "处理中...",
        message: Optional[str] = None
    ) -> ft.AlertDialog:
        """显示加载对话框
        
        Args:
            title: 标题
            message: 消息（可选）
            
        Returns:
            对话框对象（用于后续关闭）
        """
        content_items = [
            ft.ProgressRing(width=50, height=50, color=THEME.accent),
        ]
        
        if message:
            content_items.append(ft.Text(message, size=14, text_align=ft.TextAlign.CENTER))
        
        dialog = ft.AlertDialog(
            title=ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    content_items,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=15,
                ),
                padding=20,
            ),
            modal=True,
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
        
        return dialog
    
    def hide_loading(self, dialog: ft.AlertDialog) -> None:
        """隐藏加载对话框
        
        Args:
            dialog: show_loading 返回的对话框对象
        """
        dialog.open = False
        self.page.update()
    
    def show_custom_dialog(
        self,
        title: str,
        content: ft.Control,
        actions: Optional[List[ft.Control]] = None,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> ft.AlertDialog:
        """显示自定义对话框
        
        Args:
            title: 标题
            content: 内容控件
            actions: 操作按钮列表
            width: 宽度
            height: 高度
            
        Returns:
            对话框对象
        """
        dialog_content = content
        if width or height:
            dialog_content = ft.Container(
                content=content,
                width=width,
                height=height,
            )
        
        dialog = ft.AlertDialog(
            title=ft.Text(title, size=18, weight=ft.FontWeight.BOLD),
            content=dialog_content,
            actions=actions or [],
        )
        
        self.page.dialog = dialog
        dialog.open = True
        self.page.update()
        
        return dialog
    
    def close_dialog(self, dialog: Optional[ft.AlertDialog] = None) -> None:
        """关闭对话框
        
        Args:
            dialog: 对话框对象，如果为 None 则关闭当前对话框
        """
        if dialog:
            dialog.open = False
        elif self.page.dialog:
            self.page.dialog.open = False
        self.page.update()


class Toast:
    """Toast 通知组件
    
    轻量级通知，不会打断用户操作
    """
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.overlay_container: Optional[ft.Container] = None
    
    def show(
        self,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        duration_ms: int = 2000,
        position: str = "bottom"  # "top", "bottom", "center"
    ) -> None:
        """显示 Toast 通知
        
        Args:
            message: 消息内容
            notification_type: 通知类型
            duration_ms: 显示时长
            position: 位置
        """
        # 关闭时跳过通知
        if _is_closing():
            return
        
        # 图标映射
        icon_map = {
            NotificationType.SUCCESS: ft.Icons.CHECK_CIRCLE,
            NotificationType.ERROR: ft.Icons.ERROR,
            NotificationType.WARNING: ft.Icons.WARNING,
            NotificationType.INFO: ft.Icons.INFO,
        }
        
        # 颜色映射
        color_map = {
            NotificationType.SUCCESS: THEME.success,
            NotificationType.ERROR: THEME.error,
            NotificationType.WARNING: THEME.warning,
            NotificationType.INFO: THEME.info,
        }
        
        icon = icon_map.get(notification_type, ft.Icons.INFO)
        color = color_map.get(notification_type, THEME.info)
        
        # 创建 Toast 内容
        toast_content = ft.Container(
            content=ft.Row([
                ft.Icon(icon, color=color, size=20),
                ft.Text(message, color="white", size=14),
            ], spacing=10, tight=True),
            bgcolor="rgba(0, 0, 0, 0.85)",
            padding=ft.padding.all(15),
            border_radius=8,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=10,
                color="rgba(0, 0, 0, 0.3)",
            ),
        )
        
        # 添加到页面
        # 注意：Flet 可能需要使用 SnackBar 或 Overlay 实现
        # 这里展示概念性实现
        try:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Row([
                    ft.Icon(icon, color=color, size=20),
                    ft.Text(message, color="white"),
                ], spacing=10),
                bgcolor="rgba(0, 0, 0, 0.85)",
                duration=duration_ms,
            )
            self.page.snack_bar.open = True
            self.page.update()
        except Exception:
            pass


class ProgressDialog:
    """进度对话框
    
    显示长时间操作的进度
    """
    
    def __init__(self, page: ft.Page, title: str = "处理中..."):
        self.page = page
        self.title = title
        
        self.progress_bar = ft.ProgressBar(
            value=0,
            color=THEME.accent,
            bgcolor=THEME.bg_secondary,
            width=400,
        )
        
        self.progress_text = ft.Text(
            "0%",
            size=14,
            text_align=ft.TextAlign.CENTER,
        )
        
        self.status_text = ft.Text(
            "",
            size=12,
            color=THEME.text_secondary,
            text_align=ft.TextAlign.CENTER,
        )
        
        self.dialog = ft.AlertDialog(
            title=ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    self.progress_bar,
                    self.progress_text,
                    self.status_text,
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                padding=20,
                width=450,
            ),
            modal=True,
        )
    
    def show(self) -> None:
        """显示进度对话框"""
        self.page.dialog = self.dialog
        self.dialog.open = True
        self.page.update()
    
    def update_progress(self, value: float, status: str = "") -> None:
        """更新进度
        
        Args:
            value: 进度值 (0.0 - 1.0)
            status: 状态文本
        """
        self.progress_bar.value = value
        self.progress_text.value = f"{int(value * 100)}%"
        
        if status:
            self.status_text.value = status
        
        self.page.update()
    
    def hide(self) -> None:
        """隐藏进度对话框"""
        self.dialog.open = False
        self.page.update()


def show_destructive_confirmation(
    page: ft.Page,
    title: str,
    message: str,
    item_name: str,
    on_confirm: Callable
) -> None:
    """显示危险操作确认对话框（需要输入确认）
    
    Args:
        page: 页面对象
        title: 标题
        message: 消息
        item_name: 要确认的项目名称
        on_confirm: 确认回调
    """
    confirm_field = ft.TextField(
        label=f"输入 '{item_name}' 以确认",
        hint_text=item_name,
    )
    
    def handle_confirm(e):
        if confirm_field.value == item_name:
            dialog.open = False
            page.update()
            on_confirm(e)
        else:
            page.snack_bar = ft.SnackBar(
                content=ft.Text("确认文本不匹配"),
                bgcolor=THEME.error,
            )
            page.snack_bar.open = True
            page.update()
    
    def handle_cancel(e):
        dialog.open = False
        page.update()
    
    dialog = ft.AlertDialog(
        title=ft.Row([
            ft.Icon(ft.Icons.WARNING, color=THEME.error, size=24),
            ft.Text(title, size=18, weight=ft.FontWeight.BOLD),
        ], spacing=10),
        content=ft.Container(
            content=ft.Column([
                ft.Text(message, size=14),
                ft.Divider(),
                ft.Text(
                    "此操作不可撤销！",
                    size=12,
                    color=THEME.error,
                    weight=ft.FontWeight.BOLD,
                ),
                confirm_field,
            ], spacing=10),
            width=400,
        ),
        actions=[
            ft.TextButton("取消", on_click=handle_cancel),
            ft.ElevatedButton(
                "确认删除",
                on_click=handle_confirm,
                bgcolor=THEME.error,
                color="white",
            ),
        ],
    )
    
    page.dialog = dialog
    dialog.open = True
    page.update()

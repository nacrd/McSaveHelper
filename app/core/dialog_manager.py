"""Dialog Manager - 对话框管理

负责各种对话框的显示和管理，包括信息、警告、错误对话框和文件选择对话框。
"""
from dataclasses import dataclass
from typing import Callable, Optional, List
import traceback
import flet as ft

from app.adapters.file_dialogs import FileDialogPort, FileType
from app.ui.theme import THEME
from core.logger import logger

TranslateCallback = Callable[[str, str], str]


@dataclass(frozen=True)
class DialogManagerDependencies:
    page: ft.Page
    translate: TranslateCallback
    switch_view: Callable[[str], None]
    remove_view: Callable[[str], Optional[ft.Control]]
    copy_to_clipboard: Callable[[str], None]
    show_snackbar: Callable[[str, str, int], None]
    file_dialogs: FileDialogPort


class DialogManager:
    """对话框管理器

    职责：
    - 信息、警告、错误对话框
    - 文件选择对话框（目录、文件、保存）
    - 错误占位页面构建
    - 对话框生命周期管理
    """

    def __init__(self, dependencies: DialogManagerDependencies) -> None:
        self._deps = dependencies
        self.page = dependencies.page
        self._translate = dependencies.translate
        self._current_dialog: Optional[ft.AlertDialog] = None

    def close_dialog(self) -> None:
        """关闭当前打开的对话框"""
        if self._current_dialog:
            self._current_dialog.open = False
            self.page.update()
            self._current_dialog = None

    def show_dialog(
        self,
        title: str,
        message: str,
        color: str = THEME.accent,
        include_details: bool = False,
        exception: Optional[Exception] = None
    ) -> None:
        """显示对话框

        Args:
            title: 对话框标题
            message: 对话框消息
            color: 按钮颜色
            include_details: 是否包含异常详情
            exception: 异常对象
        """
        self.close_dialog()

        content, full_error_text = self._build_dialog_content(
            title, message, include_details, exception
        )
        d = self._create_alert_dialog(
            title,
            content,
            color,
            full_error_text,
            include_details,
            exception,
        )

        self._current_dialog = d
        self.page.overlay.append(d)
        d.open = True
        self.page.update()

    def _build_dialog_content(
        self,
        title: str,
        message: str,
        include_details: bool,
        exception: Optional[Exception],
    ) -> tuple:
        """构建对话框内容

        Args:
            title: 标题
            message: 消息
            include_details: 是否包含详情
            exception: 异常对象

        Returns:
            tuple: (内容控件, 完整错误文本)
        """
        content_list: List[ft.Control] = [
            ft.Text(message, color=THEME.text_secondary)
        ]
        full_error_text = f"{title}\n\n{message}"

        if include_details and exception:
            error_details = traceback.format_exc()
            full_error_text += f"\n\n详细信息：\n{error_details}"
            content_list.append(self._create_details_container(error_details))

        return ft.Column(content_list, tight=True), full_error_text

    def _create_details_container(self, error_details: str) -> ft.Container:
        """创建错误详情容器

        Args:
            error_details: 错误详情文本

        Returns:
            ft.Container: 详情容器
        """
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "详细信息：",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary,
                    ),
                    ft.Container(
                        content=ft.Text(
                            error_details,
                            size=11,
                            color=THEME.text_muted,
                            selectable=True,
                        ),
                        bgcolor=THEME.bg_secondary, padding=8, border_radius=4,
                    ),
                ],
                spacing=6, scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(top=10, right=0, bottom=0, left=0),
            height=200,
        )

    def _create_alert_dialog(
        self, title: str, content: ft.Control, color: str,
        full_error_text: str, include_details: bool, exception: Optional[Exception]
    ) -> ft.AlertDialog:
        """创建警告对话框

        Args:
            title: 标题
            content: 内容
            color: 颜色
            full_error_text: 完整错误文本
            include_details: 是否包含详情
            exception: 异常对象

        Returns:
            ft.AlertDialog: 对话框
        """
        d = ft.AlertDialog(
            title=ft.Text(title, color=THEME.text_primary),
            content=content,
            actions=[],
        )

        actions = self._create_dialog_actions(d, color, full_error_text, include_details, exception)
        d.actions = actions
        return d

    def _create_dialog_actions(
        self, dialog: ft.AlertDialog, color: str, full_error_text: str,
        include_details: bool, exception: Optional[Exception]
    ) -> List[ft.Control]:
        """创建对话框操作按钮

        Args:
            dialog: 对话框实例
            color: 按钮颜色
            full_error_text: 完整错误文本
            include_details: 是否包含详情
            exception: 异常对象

        Returns:
            List[ft.Control]: 按钮列表
        """
        actions = []

        if include_details and exception:
            actions.append(
                ft.TextButton(
                    "📋 复制错误信息",
                    style=ft.ButtonStyle(color=THEME.text_secondary),
                    on_click=lambda e: self._handle_copy(full_error_text),
                )
            )

        actions.append(
            ft.TextButton(
                self._translate("dialogs.ok", "确定"),
                style=ft.ButtonStyle(color=color),
                on_click=lambda e: self._handle_ok(dialog),
            )
        )

        return actions

    def _handle_ok(self, dialog: ft.AlertDialog) -> None:
        """处理确定按钮点击

        Args:
            dialog: 对话框实例
        """
        dialog.open = False
        self.page.update()
        self._current_dialog = None

    def _handle_copy(self, text: str) -> None:
        """处理复制按钮点击

        Args:
            text: 要复制的文本
        """
        try:
            self._deps.copy_to_clipboard(text)
            self._show_snackbar("错误信息已复制到剪贴板", THEME.mc_grass, 2000)
        except Exception:
            self._show_snackbar("复制失败，错误信息可手动选择复制", THEME.warning, 3000)

    def _show_snackbar(self, message: str, bgcolor: str, duration: int) -> None:
        """显示提示消息

        Args:
            message: 消息内容
            bgcolor: 背景颜色
            duration: 持续时间
        """
        self._deps.show_snackbar(message, bgcolor, duration)

    def info_dialog(self, title: str, message: str) -> None:
        """显示信息对话框

        Args:
            title: 对话框标题
            message: 对话框消息
        """
        self.show_dialog(title, message, THEME.accent)

    def warn_dialog(self, title: str, message: str) -> None:
        """显示警告对话框

        Args:
            title: 对话框标题
            message: 对话框消息
        """
        self.show_dialog(title, message, THEME.warning)

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False
    ) -> None:
        """显示错误对话框

        Args:
            title: 对话框标题
            message: 对话框消息
            exception: 异常对象
            show_details: 是否显示异常详情
        """
        self.show_dialog(
            title, message, THEME.error,
            include_details=show_details,
            exception=exception
        )

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True
    ) -> None:
        """统一异常处理方法

        Args:
            exception: 异常对象
            title: 对话框标题
            log: 是否记录日志
            show_dialog: 是否显示对话框
        """
        if title is None:
            title = self._translate("dialogs.error", "错误")

        # 记录日志
        if log:
            logger.error(f"{title}: {str(exception)}", module="DialogManager")
            logger.error(traceback.format_exc(), module="DialogManager")

        # 显示对话框
        if show_dialog:
            self.error_dialog(title, str(exception), exception=exception, show_details=True)

    def build_error_placeholder(self, view_id: str, error: Exception) -> ft.Container:
        """构建视图加载失败时的错误占位页面

        Args:
            view_id: 视图ID
            error: 异常对象

        Returns:
            ft.Container: 错误占位页容器
        """
        tb = traceback.format_exc()
        error_text, traceback_text = self._create_error_texts(error, tb)
        buttons = self._create_error_placeholder_buttons(view_id, tb)

        return ft.Container(
            content=ft.Column([
                self._create_error_header(view_id, buttons[0]),
                ft.Divider(height=20, color=THEME.border_subtle),
                self._create_error_message_section(error_text),
                ft.Container(height=12),
                self._create_traceback_section(traceback_text),
                ft.Container(height=20),
                ft.Row(buttons[1:], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=40,
            expand=True,
        )

    def _create_error_texts(self, error: Exception, tb: str) -> tuple:
        """创建错误文本控件

        Returns:
            tuple: (错误文本, 堆栈跟踪文本)
        """
        error_text = ft.Text(
            str(error),
            size=13,
            color=THEME.text_secondary,
            selectable=True,
        )
        traceback_text = ft.Text(
            tb,
            size=11,
            color=THEME.text_muted,
            font_family="monospace",
            selectable=True,
        )
        return error_text, traceback_text

    def _create_error_placeholder_buttons(self, view_id: str, tb: str) -> List[ft.Control]:
        """创建错误占位页按钮

        Returns:
            List[ft.Control]: 按钮列表 [关闭, 重试, 返回, 复制]
        """
        return [
            ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_color=THEME.text_secondary,
                on_click=lambda e: self._close_error_view(),
                tooltip="关闭",
            ),
            ft.Button(
                "🔄 重试",
                on_click=lambda e: self._retry_view(view_id),
                bgcolor=THEME.accent,
                color=THEME.text_primary,
            ),
            ft.OutlinedButton(
                "← 返回首页",
                on_click=lambda e: self._deps.switch_view("explorer"),
            ),
            ft.OutlinedButton(
                "📋 复制错误",
                on_click=lambda e: self._copy_error_to_clipboard(tb),
            ),
        ]

    def _create_error_header(self, view_id: str, close_btn: ft.Control) -> ft.Row:
        """创建错误页面头部

        Returns:
            ft.Row: 头部行
        """
        return ft.Row([
            ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=THEME.error),
            ft.Column([
                ft.Text(
                    f"加载页面 '{view_id}' 时出错",
                    size=18,
                    color=THEME.text_primary,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text("请检查错误信息，或尝试返回首页", size=12, color=THEME.text_muted),
            ], spacing=4),
            close_btn,
        ], spacing=16, alignment=ft.MainAxisAlignment.START)

    def _create_error_message_section(self, error_text: ft.Control) -> ft.Container:
        """创建错误信息区域

        Returns:
            ft.Container: 错误信息容器
        """
        return ft.Container(
            content=error_text, bgcolor=THEME.bg_secondary,
            border_radius=8, padding=10, width=700,
        )

    def _create_traceback_section(self, traceback_text: ft.Control) -> ft.Container:
        """创建堆栈跟踪区域

        Returns:
            ft.Container: 堆栈跟踪容器
        """
        return ft.Container(
            content=ft.Container(content=traceback_text, padding=10),
            bgcolor=THEME.bg_secondary, border_radius=8, width=700, height=250,
        )

    def _copy_error_to_clipboard(self, error_text: str) -> None:
        """复制错误信息到剪贴板

        Args:
            error_text: 要复制的错误文本
        """
        try:
            self._deps.copy_to_clipboard(error_text)
            self.info_dialog("✅ 成功", "错误信息已复制到剪贴板\n你可以直接粘贴到任何地方")
        except Exception as e:
            self.warn_dialog(
                "复制失败",
                f"无法复制到剪贴板，请手动选择并复制错误信息\n\n错误：{str(e)}"
            )

    def _close_error_view(self) -> None:
        """关闭错误页面，返回首页"""
        self._deps.remove_view("error")
        self._deps.switch_view("explorer")

    def _retry_view(self, view_id: str) -> None:
        """重试加载视图

        Args:
            view_id: 视图ID
        """
        self._deps.remove_view(view_id)
        try:
            self._deps.switch_view(view_id)
        except Exception:
            pass

    # ════════════════════════════════════════════
    #  文件选择对话框
    # ════════════════════════════════════════════

    def pick_directory(self) -> Optional[str]:
        """选择目录对话框

        Returns:
            Optional[str]: 选择的目录路径，取消则返回None
        """
        return self._deps.file_dialogs.pick_directory(
            self._translate("common.select", "选择目录")
        )

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[List[FileType]] = None
    ) -> Optional[str]:
        """选择文件对话框

        Args:
            title: 对话框标题
            file_types: 文件类型过滤

        Returns:
            Optional[str]: 选择的文件路径，取消则返回None
        """
        selected_types = file_types or [
            (self._translate("common.all_files", "所有文件"), "*.*")
        ]
        dialog_title = title or self._translate("common.select", "选择文件")
        return self._deps.file_dialogs.pick_file(
            dialog_title,
            selected_types,
        )

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[List[FileType]] = None
    ) -> Optional[str]:
        """保存文件对话框

        Args:
            title: 对话框标题
            default_ext: 默认扩展名
            file_types: 文件类型过滤

        Returns:
            Optional[str]: 选择的文件路径，取消则返回None
        """
        selected_types = file_types or [
            (self._translate("common.all_files", "所有文件"), "*.*")
        ]
        dialog_title = title or self._translate("common.save", "保存文件")
        return self._deps.file_dialogs.save_file(
            dialog_title,
            default_ext,
            selected_types,
        )

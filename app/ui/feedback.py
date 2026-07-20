"""用户反馈收集工具

提供多种用户反馈收集方式：
- 错误报告
- 功能请求
- 用户满意度调查
- 使用分析（本地匿名）
"""
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import flet as ft
from app.ui.theme import THEME


@dataclass
class FeedbackItem:
    """反馈项"""
    timestamp: datetime
    feedback_type: str  # "bug", "feature", "improvement", "other"
    title: str
    description: str
    user_email: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.feedback_type,
            "title": self.title,
            "description": self.description,
            "user_email": self.user_email,
            "metadata": self.metadata or {}
        }


@dataclass
class UsageEvent:
    """使用事件（本地匿名分析）"""
    timestamp: datetime
    event_type: str  # "feature_used", "view_opened", "action_completed"
    event_name: str
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "event_name": self.event_name,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata or {}
        }


class FeedbackCollector:
    """反馈收集器。

    应用默认实例通过模块级 feedback_collector 暴露；测试可直接构造新实例。
    """

    def __init__(self) -> None:
        self.enabled: bool = True
        self.feedback_dir: Path = Path.home() / ".mcsavehelper" / "feedback"
        self.feedback_dir.mkdir(parents=True, exist_ok=True)

        self.feedback_file: Path = self.feedback_dir / "feedback.jsonl"
        self.usage_file: Path = self.feedback_dir / "usage.jsonl"

    def collect_feedback(
        self,
        feedback_type: str,
        title: str,
        description: str,
        user_email: Optional[str] = None,
        **metadata
    ) -> None:
        """收集用户反馈

        Args:
            feedback_type: 反馈类型
            title: 标题
            description: 详细描述
            user_email: 用户邮箱（可选）
            **metadata: 额外元数据
        """
        if not self.enabled:
            return

        feedback = FeedbackItem(
            timestamp=datetime.now(),
            feedback_type=feedback_type,
            title=title,
            description=description,
            user_email=user_email,
            metadata=metadata
        )

        try:
            with open(self.feedback_file, "a", encoding="utf-8") as f:
                payload = json.dumps(
                    feedback.to_dict(),
                    ensure_ascii=False,
                )
                f.write(payload + "\n")
        except (OSError, TypeError, ValueError) as e:
            print(f"[ERROR] 保存反馈失败: {e}")

    def track_usage(
        self,
        event_type: str,
        event_name: str,
        duration_ms: Optional[float] = None,
        **metadata
    ) -> None:
        """跟踪使用事件（本地匿名）

        Args:
            event_type: 事件类型
            event_name: 事件名称
            duration_ms: 持续时间（毫秒）
            **metadata: 额外元数据
        """
        if not self.enabled:
            return

        event = UsageEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            event_name=event_name,
            duration_ms=duration_ms,
            metadata=metadata
        )

        try:
            with open(self.usage_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError) as e:
            print(f"[ERROR] 保存使用事件失败: {e}")

    def get_feedback_stats(self) -> Dict[str, int]:
        """获取反馈统计

        Returns:
            各类反馈的数量
        """
        stats: Dict[str, int] = {}

        try:
            if not self.feedback_file.exists():
                return stats

            with open(self.feedback_file, "r", encoding="utf-8") as f:
                for line in f:
                    feedback = json.loads(line)
                    feedback_type = feedback.get("type", "other")
                    stats[feedback_type] = stats.get(feedback_type, 0) + 1
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"[ERROR] 读取反馈统计失败: {e}")

        return stats

    def get_feature_usage_stats(self) -> Dict[str, int]:
        """获取功能使用统计

        Returns:
            各功能的使用次数
        """
        stats: Dict[str, int] = {}

        try:
            if not self.usage_file.exists():
                return stats

            with open(self.usage_file, "r", encoding="utf-8") as f:
                for line in f:
                    event = json.loads(line)
                    if event.get("event_type") == "feature_used":
                        feature = event.get("event_name", "unknown")
                        stats[feature] = stats.get(feature, 0) + 1
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"[ERROR] 读取使用统计失败: {e}")

        return stats


# 全局反馈收集器
feedback_collector = FeedbackCollector()


class FeedbackDialog:
    """反馈对话框

    提供友好的UI供用户提交反馈
    """

    def __init__(self, page: ft.Page, on_submit: Optional[Callable] = None):
        self.page = page
        self.on_submit_callback = on_submit
        self.feedback_type = ft.Dropdown(
            label="反馈类型",
            options=[
                ft.dropdown.Option("bug", "错误报告"),
                ft.dropdown.Option("feature", "功能请求"),
                ft.dropdown.Option("improvement", "改进建议"),
                ft.dropdown.Option("other", "其他"),
            ],
            value="bug",
            width=200,
        )
        self.title_field = ft.TextField(
            label="标题",
            hint_text="简要描述您的反馈",
            max_length=100,
        )
        self.description_field = ft.TextField(
            label="详细描述",
            hint_text="请提供更多细节...",
            multiline=True,
            min_lines=5,
            max_lines=10,
        )
        self.email_field = ft.TextField(
            label="您的邮箱（可选）",
            hint_text="如需回复，请留下邮箱",
        )
        self.dialog = ft.AlertDialog(
            title=ft.Text("提交反馈", size=20, weight=ft.FontWeight.BOLD),
            content=self._build_dialog_content(),
            actions=[
                ft.TextButton("取消", on_click=self._on_cancel),
                ft.ElevatedButton("提交", on_click=self._on_submit),
            ],
        )

    def _build_dialog_content(self) -> ft.Container:
        return ft.Container(
            content=ft.Column([
                self.feedback_type,
                self.title_field,
                self.description_field,
                self.email_field,
                ft.Text(
                    "感谢您的反馈！这将帮助我们改进产品。",
                    size=12,
                    color="grey",
                    italic=True,
                ),
            ], spacing=15, scroll=ft.ScrollMode.AUTO),
            width=500,
            height=500,
        )

    def show(self) -> None:
        """显示对话框"""
        self.page.show_dialog(self.dialog)

    def _on_cancel(self, e) -> None:
        """取消按钮回调"""
        self.dialog.open = False
        self.page.update()

    def _on_submit(self, e) -> None:
        """提交按钮回调"""
        # 验证输入
        if not self.title_field.value or not self.description_field.value:
            self.page.show_dialog(ft.SnackBar(
                content=ft.Text("请填写标题和描述"),
                bgcolor=THEME.error,
            ))
            return

        # 收集反馈
        feedback_collector.collect_feedback(
            feedback_type=self.feedback_type.value or "other",
            title=self.title_field.value,
            description=self.description_field.value,
            user_email=self.email_field.value or None,
        )

        # 关闭对话框
        self.dialog.open = False

        # 显示成功消息
        self.page.show_dialog(ft.SnackBar(
            content=ft.Text("感谢您的反馈！"),
            bgcolor=THEME.success,
        ))

        # 调用回调
        if self.on_submit_callback:
            self.on_submit_callback()

        # 重置表单
        self.title_field.value = ""
        self.description_field.value = ""
        self.email_field.value = ""


class ErrorReportDialog:
    """错误报告对话框

    自动捕获错误信息并提供报告选项
    """

    def __init__(
        self,
        page: ft.Page,
        error: Exception,
        context: Optional[str] = None
    ):
        self.page = page
        self.error = error
        self.context = context

        # 生成错误信息
        import traceback
        self.error_details = "".join(traceback.format_exception(
            type(error), error, error.__traceback__
        ))

        # 对话框内容
        self.dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.ERROR_OUTLINE, color=THEME.error, size=30),
                ft.Text("应用程序错误", size=20, weight=ft.FontWeight.BOLD),
            ], spacing=10),
            content=ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"发生了一个错误：{str(error)}",
                        size=14,
                    ),
                    ft.Divider(),
                    ft.Text("错误详情：", size=12, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        content=ft.Text(
                            self.error_details,
                            size=10,
                            font_family="monospace",
                            selectable=True,
                        ),
                        bgcolor=THEME.bg_secondary,
                        padding=10,
                        border_radius=5,
                        height=200,
                    ),
                    ft.Checkbox(
                        label="自动发送错误报告（帮助改进产品）",
                        value=True,
                    ),
                ], spacing=10, scroll=ft.ScrollMode.AUTO),
                width=600,
                height=400,
            ),
            actions=[
                ft.TextButton("关闭", on_click=self._on_close),
                ft.ElevatedButton(
                    "复制错误信息",
                    icon=ft.Icons.COPY,
                    on_click=self._on_copy,
                ),
            ],
        )

    def show(self) -> None:
        """显示错误对话框"""
        # 自动收集错误报告
        feedback_collector.collect_feedback(
            feedback_type="bug",
            title=f"自动错误报告: {type(self.error).__name__}",
            description=self.error_details,
            context=self.context,
        )

        self.page.show_dialog(self.dialog)

    def _on_close(self, e) -> None:
        """关闭对话框"""
        self.dialog.open = False
        self.page.update()

    def _on_copy(self, e) -> None:
        """复制错误信息到剪贴板"""
        self.page.run_task(self.page.clipboard.set, self.error_details)
        self.page.show_dialog(ft.SnackBar(
            content=ft.Text("错误信息已复制到剪贴板"),
            bgcolor=THEME.success,
        ))


def track_feature_usage(feature_name: str) -> Callable:
    """功能使用跟踪装饰器

    自动跟踪函数调用

    Args:
        feature_name: 功能名称

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            import time
            start = time.perf_counter()

            try:
                result = func(*args, **kwargs)
                duration = (time.perf_counter() - start) * 1000

                feedback_collector.track_usage(
                    event_type="feature_used",
                    event_name=feature_name,
                    duration_ms=duration,
                    success=True
                )

                return result
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000

                feedback_collector.track_usage(
                    event_type="feature_used",
                    event_name=feature_name,
                    duration_ms=duration,
                    success=False,
                    error=str(e)
                )

                raise

        return wrapper
    return decorator

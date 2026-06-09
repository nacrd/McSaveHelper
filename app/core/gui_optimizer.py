"""GUI Optimizer - GUI优化功能集成

负责性能监控、键盘快捷键、卡死检测、通知管理和可访问性验证的初始化和管理。
"""
from typing import TYPE_CHECKING, Any
import flet as ft

from app.ui.keyboard_shortcuts import (
    shortcut_manager,
    register_default_shortcuts,
    ModifierKey
)
from app.ui.performance import (
    perf_monitor,
    resource_monitor,
    Timer,
    health_monitor,
    AlertLevel
)
from app.ui.hang_detector import get_hang_detector
from app.ui.notifications import NotificationManager
from app.ui.accessibility import validate_theme_accessibility
from core.logger import logger

if TYPE_CHECKING:
    from app.application import Application


class GUIOptimizer:
    """GUI优化管理器

    职责：
    - 性能监控初始化
    - 键盘快捷键注册
    - 卡死检测器管理
    - 通知管理器集成
    - 可访问性验证
    """

    def __init__(self, app: "Application") -> None:
        """初始化GUI优化管理器

        Args:
            app: 应用实例
        """
        self.app = app
        self.page = app.page
        self.notification_manager = None
        self._heartbeat_active = False
        self._hang_detector_active = False

    def initialize(self) -> None:
        """初始化GUI优化功能"""
        try:
            # 1. 初始化通知管理器
            self.notification_manager = NotificationManager(self.page)

            # 2. 启用卡死检测器（静默启用）
            hang_detector = get_hang_detector()
            hang_detector.enable()
            self._start_hang_detector_heartbeat()

            # 3. 根据配置启用性能监控（可选）
            enable_perf = self.app.config.ui_settings.get(
                "enable_performance_monitor", False
            )

            if enable_perf:
                perf_monitor.enable()
                resource_monitor.start()
                interval = float(
                    self.app.config.ui_settings.get("performance_print_interval", 60)
                )
                resource_monitor.set_print_interval(max(5.0, interval))
                # 配置健康监控告警回调
                health_monitor.set_alert_callback(self._on_health_alert)
                self._start_heartbeat()

            # 4. 注册键盘快捷键
            register_default_shortcuts(
                on_save=self._shortcut_save_config,
                on_help=self._shortcut_show_help,
                on_refresh=self._shortcut_refresh
            )

            # 注册应用特定快捷键
            shortcut_manager.register(
                "show_feedback",
                "f",
                self._shortcut_show_feedback,
                "显示反馈对话框",
                [ModifierKey.CTRL]
            )

            # 设置键盘事件处理
            self.page.on_keyboard_event = self._on_keyboard_event

            # 5. 验证可访问性
            accessibility_results = validate_theme_accessibility()
            failed_checks = [
                name for name, result in accessibility_results.items()
                if not result["passes"]
            ]
            if failed_checks:
                logger.warning(
                    f"可访问性检查: {len(failed_checks)} 项未通过",
                    module="GUIOptimizer"
                )
            else:
                logger.info("可访问性检查: 全部通过", module="GUIOptimizer")

            logger.info("GUI 优化模块初始化完成", module="GUIOptimizer")

        except Exception as e:
            logger.error(f"GUI 优化模块初始化失败: {e}", module="GUIOptimizer")
            # 降级：不使用优化功能
            self.notification_manager = None

    def _on_keyboard_event(self, e: ft.KeyboardEvent) -> None:
        """处理键盘事件

        Args:
            e: 键盘事件
        """
        try:
            shortcut_manager.handle_event(e)
        except Exception as ex:
            logger.error(f"键盘事件处理失败: {ex}", module="GUIOptimizer")

    def _shortcut_save_config(self, e) -> None:
        """快捷键：保存配置 (Ctrl+S)

        Args:
            e: 事件对象
        """
        try:
            with Timer("save_config"):
                self.app.config.save()
            logger.info("配置已保存", module="GUIOptimizer")
            if self.notification_manager:
                self.notification_manager.show_success("配置保存成功")
        except Exception as ex:
            logger.error(f"保存配置失败: {ex}", module="GUIOptimizer")
            if self.notification_manager:
                self.notification_manager.show_error("保存配置失败")

    def _shortcut_show_help(self, e) -> None:
        """快捷键：显示帮助 (F1)

        Args:
            e: 事件对象
        """
        try:
            help_dialog = shortcut_manager.create_help_dialog()
            self.page.dialog = help_dialog
            help_dialog.open = True
            self.page.update()
        except Exception as ex:
            logger.error(f"显示帮助失败: {ex}", module="GUIOptimizer")

    def _shortcut_refresh(self, e) -> None:
        """快捷键：刷新页面 (F5)

        Args:
            e: 事件对象
        """
        try:
            logger.info("刷新页面", module="GUIOptimizer")
            self.page.update()
            if self.notification_manager:
                self.notification_manager.show_info("页面已刷新")
        except Exception as ex:
            logger.error(f"刷新页面失败: {ex}", module="GUIOptimizer")

    def _shortcut_show_feedback(self, e) -> None:
        """快捷键：显示反馈对话框 (Ctrl+F)

        Args:
            e: 事件对象
        """
        try:
            from app.ui.feedback import FeedbackDialog
            feedback_dialog = FeedbackDialog(self.page)
            feedback_dialog.show()
        except Exception as ex:
            logger.error(f"显示反馈对话框失败: {ex}", module="GUIOptimizer")

    def _on_health_alert(self, alert) -> None:
        """健康告警回调

        Args:
            alert: 告警对象
        """
        # 关闭时不显示告警通知
        try:
            from app.ui.utils import is_app_closing
            if is_app_closing():
                return
        except Exception:
            pass

        if not self.notification_manager:
            return

        try:
            if alert.level == AlertLevel.CRITICAL:
                async def _show_error(message: str):
                    self.notification_manager.show_error(message, duration_ms=8000)
                self.page.run_task(_show_error, alert.message)
            else:
                async def _show_warning(message: str):
                    self.notification_manager.show_warning(message, duration_ms=5000)
                self.page.run_task(_show_warning, alert.message)
        except Exception:
            pass

    def _start_heartbeat(self) -> None:
        """启动UI心跳线程，用于性能监控"""
        import threading

        def _beat_loop():
            while self._heartbeat_active:
                health_monitor.heartbeat()
                threading.Event().wait(3.0)

        self._heartbeat_active = True
        t = threading.Thread(target=_beat_loop, daemon=True)
        t.start()

    def _start_hang_detector_heartbeat(self) -> None:
        """启动独立的卡死检测器心跳线程"""
        import threading

        def _hang_beat_loop():
            hang_detector = get_hang_detector()
            while self._hang_detector_active:
                hang_detector.ui_heartbeat()
                threading.Event().wait(2.0)

        self._hang_detector_active = True
        t = threading.Thread(
            target=_hang_beat_loop,
            daemon=True,
            name="HangDetectorHeartbeat"
        )
        t.start()

    def stop(self) -> None:
        """停止GUI优化功能"""
        self._heartbeat_active = False
        self._hang_detector_active = False

        try:
            perf_monitor.disable()
            resource_monitor.stop()
        except Exception:
            pass

"""GUI Optimizer - GUI优化功能集成

负责性能监控、键盘快捷键、卡死检测、通知管理和可访问性验证的初始化和管理。
"""
from dataclasses import dataclass
import threading
from typing import Any, Callable, Optional, Protocol, cast
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
from core.performance import PerformanceMetrics, set_metrics_sink


class ShortcutManagerPort(Protocol):
    def register(
        self,
        binding_id: str,
        key: str,
        callback: Callable[..., Any],
        description: str,
        modifiers: list[Any],
    ) -> None:
        ...

    def handle_event(self, e: ft.KeyboardEvent) -> bool:
        ...

    def create_help_dialog(self) -> Any:
        ...


class PerformanceMonitorPort(Protocol):
    enabled: bool

    def enable(self) -> None:
        ...

    def disable(self) -> None:
        ...

    def record(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        **metadata: Any,
    ) -> None:
        ...


class ResourceMonitorPort(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def set_print_interval(self, seconds: float) -> None:
        ...


class HealthMonitorPort(Protocol):
    def set_alert_callback(self, callback: Callable[[Any], None]) -> None:
        ...

    def heartbeat(self) -> None:
        ...


@dataclass(frozen=True)
class GUIOptimizerDependencies:
    page: ft.Page
    get_ui_setting: Callable[[str, Any], Any]
    save_config: Callable[[], None]
    shortcut_manager: ShortcutManagerPort = cast(
        ShortcutManagerPort,
        shortcut_manager,
    )
    performance_monitor: PerformanceMonitorPort = cast(
        PerformanceMonitorPort,
        perf_monitor,
    )
    resource_monitor: ResourceMonitorPort = cast(
        ResourceMonitorPort,
        resource_monitor,
    )
    health_monitor: HealthMonitorPort = cast(
        HealthMonitorPort,
        health_monitor,
    )


class GUIOptimizer:
    """GUI优化管理器

    职责：
    - 性能监控初始化
    - 键盘快捷键注册
    - 卡死检测器管理
    - 通知管理器集成
    - 可访问性验证
    """

    def __init__(self, dependencies: GUIOptimizerDependencies) -> None:
        self._deps = dependencies
        self.page = dependencies.page
        self._shortcut_manager = dependencies.shortcut_manager
        self._performance_monitor = dependencies.performance_monitor
        self._resource_monitor = dependencies.resource_monitor
        self._health_monitor = dependencies.health_monitor
        self.notification_manager: Optional[NotificationManager] = None
        self._heartbeat_stop = threading.Event()
        self._hang_heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._hang_heartbeat_thread: Optional[threading.Thread] = None

    def initialize(self) -> None:
        """初始化GUI优化功能"""
        try:
            # 1. 初始化通知管理器和业务指标桥接
            self.notification_manager = NotificationManager(self.page)
            set_metrics_sink(self._record_business_metric)

            # 2. 启用卡死检测器（静默启用）
            hang_detector = get_hang_detector()
            hang_detector.enable()
            self._start_hang_detector_heartbeat()

            # 3. 根据配置启用性能监控（可选）
            enable_perf = self._deps.get_ui_setting(
                "enable_performance_monitor", False
            )

            if enable_perf:
                interval = float(
                    self._deps.get_ui_setting("performance_print_interval", 60)
                )
                self.configure_performance_monitor(True, interval)

            # 4. 注册键盘快捷键
            register_default_shortcuts(
                on_save=self._shortcut_save_config,
                on_help=self._shortcut_show_help,
                on_refresh=self._shortcut_refresh
            )

            # 注册应用特定快捷键
            self._shortcut_manager.register(
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

    def _record_business_metric(self, metrics: PerformanceMetrics) -> None:
        """Adapt core business metrics to the optional GUI monitor."""
        if not self._performance_monitor.enabled:
            return
        self._performance_monitor.record(
            f"biz_{metrics.operation}",
            metrics.duration_seconds * 1000,
            "ms",
            files=metrics.files_processed,
            bytes=metrics.bytes_processed,
            errors=metrics.errors,
        )

    def _on_keyboard_event(self, e: ft.KeyboardEvent) -> None:
        """处理键盘事件

        Args:
            e: 键盘事件
        """
        try:
            self._shortcut_manager.handle_event(e)
        except Exception as ex:
            logger.error(f"键盘事件处理失败: {ex}", module="GUIOptimizer")

    def _shortcut_save_config(self, e: Any) -> None:
        """快捷键：保存配置 (Ctrl+S)

        Args:
            e: 事件对象
        """
        try:
            with Timer("save_config"):
                self._deps.save_config()
            logger.info("配置已保存", module="GUIOptimizer")
            if self.notification_manager:
                self.notification_manager.show_success("配置保存成功")
        except Exception as ex:
            logger.error(f"保存配置失败: {ex}", module="GUIOptimizer")
            if self.notification_manager:
                self.notification_manager.show_error("保存配置失败")

    def _shortcut_show_help(self, e: Any) -> None:
        """快捷键：显示帮助 (F1)

        Args:
            e: 事件对象
        """
        try:
            help_dialog = self._shortcut_manager.create_help_dialog()
            self.page.show_dialog(help_dialog)
        except Exception as ex:
            logger.error(f"显示帮助失败: {ex}", module="GUIOptimizer")

    def _shortcut_refresh(self, e: Any) -> None:
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

    def _shortcut_show_feedback(self, e: Any) -> None:
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

    def _on_health_alert(self, alert: Any) -> None:
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

        notification_manager = self.notification_manager
        if notification_manager is None:
            return

        try:
            if alert.level == AlertLevel.CRITICAL:
                async def _show_error(message: str) -> None:
                    notification_manager.show_error(message, duration_ms=8000)
                self.page.run_task(_show_error, alert.message)
            else:
                async def _show_warning(message: str) -> None:
                    notification_manager.show_warning(message, duration_ms=5000)
                self.page.run_task(_show_warning, alert.message)
        except Exception:
            pass

    def configure_performance_monitor(
        self,
        enabled: bool,
        print_interval: float = 60.0,
    ) -> None:
        """统一启停性能监控及其心跳资源。"""
        self.set_performance_print_interval(print_interval)
        if enabled:
            self._performance_monitor.enable()
            self._health_monitor.set_alert_callback(self._on_health_alert)
            self._resource_monitor.start()
            self._start_heartbeat()
            return

        self._performance_monitor.disable()
        self._resource_monitor.stop()
        self._stop_performance_heartbeat()

    def set_performance_print_interval(self, seconds: float) -> None:
        """更新资源监控的日志打印间隔。"""
        self._resource_monitor.set_print_interval(max(5.0, seconds))

    def _start_heartbeat(self) -> None:
        """启动UI心跳线程，用于性能监控"""
        thread = self._heartbeat_thread
        if thread is not None and thread.is_alive():
            return

        self._heartbeat_stop.clear()

        def _beat_loop() -> None:
            while not self._heartbeat_stop.is_set():
                self._health_monitor.heartbeat()
                self._heartbeat_stop.wait(3.0)

        self._heartbeat_thread = threading.Thread(
            target=_beat_loop,
            daemon=True,
            name="PerformanceHeartbeat",
        )
        self._heartbeat_thread.start()

    def _stop_performance_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._heartbeat_thread = None

    def _start_hang_detector_heartbeat(self) -> None:
        """启动独立的卡死检测器心跳线程"""
        thread = self._hang_heartbeat_thread
        if thread is not None and thread.is_alive():
            return

        self._hang_heartbeat_stop.clear()

        def _hang_beat_loop() -> None:
            hang_detector = get_hang_detector()
            while not self._hang_heartbeat_stop.is_set():
                hang_detector.ui_heartbeat()
                self._hang_heartbeat_stop.wait(2.0)

        self._hang_heartbeat_thread = threading.Thread(
            target=_hang_beat_loop,
            daemon=True,
            name="HangDetectorHeartbeat"
        )
        self._hang_heartbeat_thread.start()

    def _stop_hang_detector_heartbeat(self) -> None:
        self._hang_heartbeat_stop.set()
        thread = self._hang_heartbeat_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._hang_heartbeat_thread = None

    def stop(self) -> None:
        """停止GUI优化功能"""
        self.configure_performance_monitor(False)
        self._stop_hang_detector_heartbeat()
        set_metrics_sink(None)

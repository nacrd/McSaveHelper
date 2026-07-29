"""迁移结果的计时与 UI 呈现。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.services.execution_runtime import CancellationToken
from core.types import BatchResult, LogCallback


Translate = Callable[..., str]
DialogCallback = Callable[..., None]
ExceptionCallback = Callable[..., None]


class UiPublisher(Protocol):
    """把回调投递到 UI 线程并保留迁移任务身份。"""

    def __call__(
        self,
        generation: int,
        token: CancellationToken,
        callback: Callable[..., None],
        *args: object,
    ) -> None:
        """发布仅属于当前任务代数的 UI 回调。"""


@dataclass(frozen=True)
class MigrationPresentationPorts:
    """迁移结果呈现所需的 UI 端口。"""

    translate: Translate
    error_dialog: DialogCallback
    handle_exception: ExceptionCallback
    show_success: Callable[[str, str], None]
    log: LogCallback
    log_header: Callable[[str], None]
    set_progress_label: Callable[[str], None]


class OperationTimer:
    """记录单个控制器内操作的单调时钟耗时。"""

    def __init__(self) -> None:
        """创建空计时集合。"""
        self._lock = threading.Lock()
        self._started_at: dict[str, float] = {}

    def start(self, operation_id: str) -> None:
        """开始或重置指定操作计时。"""
        with self._lock:
            self._started_at[operation_id] = time.monotonic()

    def finish(self, operation_id: str) -> float | None:
        """结束指定操作并返回耗时；未开始时返回 None。"""
        with self._lock:
            started_at = self._started_at.pop(operation_id, None)
        if started_at is None:
            return None
        return time.monotonic() - started_at

    def clear(self) -> None:
        """丢弃所有仍未结束的计时。"""
        with self._lock:
            self._started_at.clear()


class MigrationResultPresenter:
    """将迁移终态转换为用户可见日志、标签和对话框。"""

    def __init__(
        self,
        ports: MigrationPresentationPorts,
        publish: UiPublisher,
    ) -> None:
        """注入呈现端口和带任务身份校验的 UI 发布器。"""
        self._ports = ports
        self._publish = publish
        self._timer = OperationTimer()

    def start_timing(self, operation_id: str) -> None:
        """开始记录一次迁移操作耗时。"""
        self._timer.start(operation_id)

    def clear_timings(self) -> None:
        """清除尚未由结果呈现消费的计时。"""
        self._timer.clear()

    def single_success(
        self,
        output_path: str,
        generation: int,
        token: CancellationToken,
    ) -> None:
        """发布单世界迁移成功结果。"""
        elapsed = self._timer.finish("migration_single")

        def render() -> None:
            ports = self._ports
            if elapsed is not None:
                ports.log(f"迁移耗时: {elapsed:.2f}秒", "INFO")
            ports.log_header(self._t("messages.migration_complete", "迁移完成"))
            success_message = self._t(
                "messages.migration_success",
                "迁移完成！输出目录: {output_path}",
                output_path=output_path,
            )
            ports.log(success_message, "SUCCESS")
            ports.set_progress_label(self._t("top_bar.completed", "已完成"))
            ports.show_success(
                self._t("dialogs.success", "成功"),
                success_message,
            )

        self._publish(generation, token, render)

    def single_failure(
        self,
        error: BaseException,
        generation: int,
        token: CancellationToken,
    ) -> None:
        """发布单世界迁移失败结果。"""
        self._timer.finish("migration_single")
        error_message = self._t(
            "messages.migration_exception",
            "迁移失败: {error}",
            error=str(error),
        )

        def render() -> None:
            ports = self._ports
            ports.handle_exception(
                error,
                title=error_message,
                log=True,
                show_dialog=False,
            )
            ports.set_progress_label(self._t("top_bar.failed", "失败"))
            ports.error_dialog(
                self._t("dialogs.error", "错误"),
                error_message,
                exception=error,
                show_details=True,
            )

        self._publish(generation, token, render)

    def batch_success(
        self,
        results: BatchResult,
        generation: int,
        token: CancellationToken,
    ) -> None:
        """发布批量迁移汇总结果。"""
        elapsed = self._timer.finish("migration_batch")
        success = sum(
            1 for result in results.values() if bool(result.get("success"))
        )
        cancelled = sum(
            1 for result in results.values() if bool(result.get("cancelled"))
        )
        failed = len(results) - success - cancelled

        def render() -> None:
            self._render_batch_success(
                elapsed,
                success,
                failed,
                cancelled,
                len(results),
            )

        self._publish(generation, token, render)

    def batch_failure(
        self,
        error: BaseException,
        generation: int,
        token: CancellationToken,
    ) -> None:
        """发布批量迁移失败结果。"""
        self._timer.finish("migration_batch")
        title = self._t(
            "messages.save_failed",
            "批量处理失败: {error}",
            error=str(error),
        )

        def render() -> None:
            self._ports.handle_exception(
                error,
                title=title,
                log=True,
                show_dialog=False,
            )
            self._ports.set_progress_label(
                self._t("top_bar.batch_failed", "批量处理失败")
            )

        self._publish(generation, token, render)

    def _render_batch_success(
        self,
        elapsed: float | None,
        success: int,
        failed: int,
        cancelled: int,
        total: int,
    ) -> None:
        ports = self._ports
        if elapsed is not None:
            ports.log(f"批量迁移耗时: {elapsed:.2f}秒", "INFO")
        ports.log_header(
            self._t(
                "messages.batch_migration_complete_header",
                "批量处理完成",
            )
        )
        ports.log(
            self._t(
                "messages.batch_migration_complete",
                "成功: {success}/{total}",
                success=success,
                total=total,
            ),
            "SUCCESS" if success == total else "WARN",
        )
        if success == total:
            label = self._t("top_bar.batch_completed", "批量处理完成")
        else:
            label = self._t("top_bar.batch_partial", "批量处理部分完成")
            ports.log(
                self._t(
                    "messages.batch_result_details",
                    "失败: {failed}，取消: {cancelled}",
                    failed=failed,
                    cancelled=cancelled,
                ),
                "WARN",
            )
        ports.set_progress_label(label)

    def _t(self, key: str, default: str = "", **kwargs: Any) -> str:
        return self._ports.translate(key, default, **kwargs)


__all__ = [
    "MigrationPresentationPorts",
    "MigrationResultPresenter",
    "OperationTimer",
    "UiPublisher",
]

"""UI-independent performance tracking for business operations.

业务指标通过 ``set_metrics_sink`` 投递；UI 适配器应使用
``core.observability.metrics_to_operation_record`` 转为统一协议。
"""
import time
import threading
from typing import Optional, Dict, Any, Callable, Iterator
from dataclasses import dataclass, field
from contextlib import contextmanager

from core.observability import OperationRecord, metrics_to_operation_record


@dataclass
class PerformanceMetrics:
    """性能指标数据类"""

    operation: str
    duration_seconds: float
    memory_peak_mb: float
    memory_delta_mb: float
    files_processed: int = 0
    bytes_processed: int = 0
    errors: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_operation_record(
        self,
        *,
        feature: str = "business",
        world_id: str = "",
    ) -> OperationRecord:
        """转换为统一 ``OperationRecord`` 供 UI/日志适配。"""
        return metrics_to_operation_record(
            self,
            feature=feature,
            world_id=world_id,
        )

    @property
    def throughput_files_per_sec(self) -> float:
        """文件处理吞吐量（文件/秒）；时长为 0 时返回 0。"""
        if self.duration_seconds > 0 and self.files_processed > 0:
            return self.files_processed / self.duration_seconds
        return 0.0

    @property
    def throughput_mb_per_sec(self) -> float:
        """数据吞吐量（MB/秒）。"""
        if self.duration_seconds > 0 and self.bytes_processed > 0:
            return (self.bytes_processed / (1024 * 1024)) / \
                self.duration_seconds
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可 JSON 化的指标字典。"""
        return {
            "operation": self.operation,
            "duration_seconds": round(
                self.duration_seconds,
                3),
            "memory_peak_mb": round(
                self.memory_peak_mb,
                2),
            "memory_delta_mb": round(
                self.memory_delta_mb,
                2),
            "files_processed": self.files_processed,
            "bytes_processed": self.bytes_processed,
            "errors": self.errors,
            "throughput_files_per_sec": round(
                self.throughput_files_per_sec,
                2),
            "throughput_mb_per_sec": round(
                self.throughput_mb_per_sec,
                2),
            "metadata": self.metadata,
        }

    def summary_line(self) -> str:
        """一行摘要，用于日志输出"""
        parts = [f"{self.operation}: {self.duration_seconds:.3f}s"]
        if self.files_processed > 0:
            parts.append(f"{self.files_processed}文件")
        if self.bytes_processed > 0:
            parts.append(f"{self.bytes_processed / (1024 * 1024):.1f}MB")
        if self.memory_peak_mb > 0:
            parts.append(f"内存峰值{self.memory_peak_mb:.1f}MB")
        if self.errors > 0:
            parts.append(f"{self.errors}个错误")
        return ", ".join(parts)

    def __str__(self) -> str:
        lines = [
            f"=== 性能指标: {self.operation} ===",
            f"耗时: {self.duration_seconds:.3f}秒",
            f"内存峰值: {self.memory_peak_mb:.2f}MB",
            f"内存增量: {self.memory_delta_mb:.2f}MB",
            f"处理文件: {self.files_processed}个",
            f"处理数据: {self.bytes_processed / (1024 * 1024):.2f}MB",
        ]
        if self.throughput_files_per_sec > 0:
            lines.append(f"文件吞吐量: {self.throughput_files_per_sec:.2f}文件/秒")
        if self.throughput_mb_per_sec > 0:
            lines.append(f"数据吞吐量: {self.throughput_mb_per_sec:.2f}MB/秒")
        if self.errors > 0:
            lines.append(f"错误数: {self.errors}")
        if self.metadata:
            lines.append("额外信息:")
            for key, value in self.metadata.items():
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)


class PerfTracker:
    """业务性能追踪器

    - 通过 track() 上下文管理器追踪操作耗时和内存
    - 自动通过 core.logger 输出日志
    - 可将完成的指标发送给调用方注入的接收器

    示例:
        >>> tracker = PerfTracker()
        >>> with tracker.track("区域文件扫描") as t:
        ...     for f in scan_all_regions(path):
        ...         t.increment_files(1)
        >>> print(tracker.get_metrics("区域文件扫描"))
    """

    def __init__(
        self,
        metrics_sink: Optional[Callable[[PerformanceMetrics], None]] = None,
    ) -> None:
        """构造追踪器。

        Args:
            metrics_sink: 每次 track 结束时可选接收完整指标的回调。
        """
        self._metrics: Dict[str, PerformanceMetrics] = {}
        self._lock = threading.Lock()
        self._local = threading.local()
        self._metrics_sink = metrics_sink
        # 尝试导入 psutil 用于内存采样
        try:
            import psutil  # type: ignore
            self._process = psutil.Process()
        except ImportError:
            self._process = None

    def _get_memory_mb(self) -> float:
        """获取当前进程内存（MB）"""
        if self._process is not None:
            try:
                return float(self._process.memory_info().rss) / 1024 / 1024
            except (OSError, AttributeError, TypeError, ValueError):
                pass
        return 0.0

    def set_metrics_sink(
        self,
        sink: Optional[Callable[[PerformanceMetrics], None]],
    ) -> None:
        """Set the optional adapter that consumes completed metrics."""
        with self._lock:
            self._metrics_sink = sink

    def _publish_metrics(self, metrics: PerformanceMetrics) -> None:
        with self._lock:
            sink = self._metrics_sink
        if sink is None:
            return
        try:
            sink(metrics)
        except Exception:
            # Instrumentation must never fail the operation being measured.
            pass

    def _log_metrics(self, metrics: PerformanceMetrics) -> None:
        """通过 core.logger 输出性能日志。"""
        try:
            from core.logger import logger as _logger
            _logger.info(metrics.summary_line(), module="Perf")
        except Exception:
            # Logger may be unavailable during early bootstrap/teardown.
            print(f"[Perf] {metrics.summary_line()}")

    @contextmanager
    def track(
        self,
        operation: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Iterator["PerfTracker"]:
        """追踪操作的性能指标。

        Args:
            operation: 操作名称。
            metadata: 额外元数据。

        Yields:
            PerfTracker: 当前 tracker 实例，供操作内部累加计数。
        """
        start_time = time.perf_counter()
        start_memory = self._get_memory_mb()

        with self._lock:
            metric = self._metrics.get(operation)
            if metric is None:
                metric = PerformanceMetrics(
                    operation=operation,
                    duration_seconds=0.0,
                    memory_peak_mb=0.0,
                    memory_delta_mb=0.0,
                    metadata=dict(metadata or {}),
                )
                self._metrics[operation] = metric
            elif metadata:
                metric.metadata.update(metadata)
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
        stack.append(metric)

        try:
            yield self
        finally:
            duration = time.perf_counter() - start_time
            current_mem = self._get_memory_mb()
            memory_delta = current_mem - start_memory if current_mem > 0 else 0.0
            memory_peak = current_mem if current_mem > 0 else 0.0

            with self._lock:
                metric.duration_seconds += duration
                metric.memory_peak_mb = max(metric.memory_peak_mb, memory_peak)
                metric.memory_delta_mb += memory_delta

            self._log_metrics(metric)
            self._publish_metrics(metric)
            stack.pop()

    def _current_metric(self) -> Optional[PerformanceMetrics]:
        stack = getattr(self._local, "stack", None)
        return stack[-1] if stack else None

    def increment_files(self, count: int = 1) -> None:
        """增加处理的文件计数"""
        metric = self._current_metric()
        if metric is not None:
            with self._lock:
                metric.files_processed += count

    def increment_bytes(self, bytes_count: int) -> None:
        """增加处理的字节数"""
        metric = self._current_metric()
        if metric is not None:
            with self._lock:
                metric.bytes_processed += bytes_count

    def increment_errors(self, count: int = 1) -> None:
        """增加错误计数"""
        metric = self._current_metric()
        if metric is not None:
            with self._lock:
                metric.errors += count

    def add_metadata(self, key: str, value: Any) -> None:
        """添加元数据到当前操作"""
        metric = self._current_metric()
        if metric is not None:
            with self._lock:
                metric.metadata[key] = value

    def get_metrics(self, operation: str) -> Optional[PerformanceMetrics]:
        """获取指定操作的性能指标"""
        with self._lock:
            return self._metrics.get(operation)

    def get_all_metrics(self) -> Dict[str, PerformanceMetrics]:
        """获取所有操作的性能指标"""
        with self._lock:
            return self._metrics.copy()

    def clear(self) -> None:
        """清除所有性能指标"""
        with self._lock:
            self._metrics.clear()


# 全局追踪器
_tracker: Optional[PerfTracker] = None
_tracker_lock = threading.Lock()


def get_tracker() -> PerfTracker:
    """获取全局业务性能追踪器（线程安全单例）"""
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = PerfTracker()
    return _tracker


def set_metrics_sink(
    sink: Optional[Callable[[PerformanceMetrics], None]],
) -> None:
    """Attach an infrastructure/UI metrics adapter to the global tracker."""
    get_tracker().set_metrics_sink(sink)


def reset_tracker() -> None:
    """重置全局追踪器"""
    global _tracker
    with _tracker_lock:
        if _tracker is not None:
            _tracker.clear()
        _tracker = None

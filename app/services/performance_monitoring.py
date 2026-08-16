"""Qt/Flet 无关的进程资源性能监控服务。"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psutil

from core.logger import logger


@dataclass(frozen=True)
class PerformanceMetric:
    """一次资源采样。"""

    timestamp: datetime
    metric_name: str
    value: float
    unit: str


class PerformanceMonitoringService:
    """有界保存进程资源采样，并按配置周期输出摘要。"""

    def __init__(self, max_samples: int = 1000) -> None:
        """创建未启动的监控服务。

        Args:
            max_samples: 每种指标最多保留的样本数。

        Raises:
            ValueError: 样本容量小于一。
        """
        if max_samples < 1:
            raise ValueError("性能指标容量必须至少为 1")
        self._max_samples = max_samples
        self._metrics: dict[str, deque[PerformanceMetric]] = {}
        self._metrics_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._process = psutil.Process()
        self._sample_interval = 2.0
        self._print_interval = 60.0
        self._samples_since_print = 0

    @property
    def enabled(self) -> bool:
        """返回采样线程是否处于活动状态。"""
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def print_interval(self) -> float:
        """返回当前摘要打印间隔。"""
        with self._lifecycle_lock:
            return self._print_interval

    def configure(self, enabled: bool, print_interval: float = 60.0) -> None:
        """应用启停状态与摘要打印间隔。"""
        self.set_print_interval(print_interval)
        if enabled:
            self.start()
        else:
            self.stop()

    def set_print_interval(self, seconds: float) -> None:
        """设置摘要打印间隔，最小五秒。"""
        with self._lifecycle_lock:
            self._print_interval = max(5.0, float(seconds))

    def start(self) -> None:
        """启动后台采样；已启动时保持幂等。"""
        with self._lifecycle_lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                return
            self._stop_event.clear()
            self._samples_since_print = 0
            self._process.cpu_percent()
            self._thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="PerformanceMonitor",
            )
            self._thread.start()

    def stop(self) -> None:
        """停止采样并等待线程退出；可重复调用。"""
        with self._lifecycle_lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._sample_interval + 1.0)
        with self._lifecycle_lock:
            if self._thread is thread and (
                thread is None or not thread.is_alive()
            ):
                self._thread = None

    def snapshot(self, metric_name: str) -> tuple[PerformanceMetric, ...]:
        """返回指定指标的稳定样本快照。"""
        with self._metrics_lock:
            return tuple(self._metrics.get(metric_name, ()))

    def clear(self) -> None:
        """清空已收集样本。"""
        with self._metrics_lock:
            self._metrics.clear()

    def _monitor_loop(self) -> None:
        try:
            while not self._stop_event.wait(self._sample_interval):
                self._sample_once()
        except (OSError, psutil.Error) as error:
            logger.warning(
                f"性能监控已停止: {error}",
                module="PerformanceMonitor",
            )
        finally:
            with self._lifecycle_lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _sample_once(self) -> None:
        memory_mb = self._process.memory_info().rss / 1024 / 1024
        cpu_percent = self._process.cpu_percent()
        now = datetime.now()
        self._append(PerformanceMetric(now, "memory_usage", memory_mb, "MB"))
        self._append(PerformanceMetric(now, "cpu_usage", cpu_percent, "%"))
        self._samples_since_print += 1
        threshold = max(1, int(self.print_interval / self._sample_interval))
        if self._samples_since_print >= threshold:
            self._samples_since_print = 0
            self._log_summary(memory_mb, cpu_percent)

    def _append(self, metric: PerformanceMetric) -> None:
        with self._metrics_lock:
            samples = self._metrics.setdefault(
                metric.metric_name,
                deque(maxlen=self._max_samples),
            )
            samples.append(metric)

    @staticmethod
    def _log_summary(memory_mb: float, cpu_percent: float) -> None:
        logger.info(
            f"进程资源: memory={memory_mb:.2f} MB, cpu={cpu_percent:.1f}%",
            module="PerformanceMonitor",
        )

    def close(self) -> None:
        """释放采样线程。"""
        self.stop()


__all__ = ["PerformanceMetric", "PerformanceMonitoringService"]

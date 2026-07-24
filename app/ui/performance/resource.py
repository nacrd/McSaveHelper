"""资源使用监控模块

监控 CPU、内存等系统资源使用情况，并定期输出摘要到日志。
"""
import time
import threading
from typing import Any, Optional, Protocol

try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False


class PerformanceMonitorPort(Protocol):
    """性能指标记录与汇总端口。"""

    def record(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        **metadata: Any,
    ) -> None:
        """记录单次指标采样。

        Args:
            metric_name: 指标名。
            value: 采样值。
            unit: 单位（如 MB、%）。
            **metadata: 可选附加元数据。
        """
        ...

    def summary(self) -> dict:
        """返回各指标的统计摘要字典。"""
        ...

    def get_memory_usage(self) -> float:
        """返回当前内存占用（MB）。"""
        ...

    def get_cpu_percent(self) -> float:
        """返回当前 CPU 使用率百分比。"""
        ...


class HealthMonitorPort(Protocol):
    """健康检查端口：根据资源采样触发告警逻辑。"""

    def check(
        self,
        cpu_percent: float,
        memory_mb: float,
        check_threads: bool = True,
    ) -> None:
        """根据 CPU/内存采样执行健康检查。

        Args:
            cpu_percent: CPU 使用率。
            memory_mb: 内存占用 MB。
            check_threads: 是否检查线程数。
        """
        ...


class ResourceUsageMonitor:
    """资源使用监控器。

    后台采样进程 CPU/内存，写入性能端口，并按间隔把摘要打到日志。
    无 psutil 时 ``start`` 为空操作。
    """

    def __init__(
        self,
        sample_interval: float = 2.0,
        print_interval: float = 120.0,
        *,
        performance_monitor: Optional[PerformanceMonitorPort] = None,
        health_monitor: Optional[HealthMonitorPort] = None,
    ) -> None:
        """创建监控器。

        Args:
            sample_interval: 采样间隔秒。
            print_interval: 摘要日志间隔秒（最小 5）。
            performance_monitor: 可选性能端口；None 时懒加载默认实例。
            health_monitor: 可选健康端口；None 时懒加载默认实例。
        """
        self.sample_interval = sample_interval
        self.print_interval = print_interval
        self._performance_monitor = performance_monitor
        self._health_monitor = health_monitor
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._process: Any = (
            psutil.Process()
            if _PSUTIL_AVAILABLE and psutil is not None
            else None
        )
        self._last_print_time: float = 0.0
        self._sample_count = 0
        self._thread_check_interval = 10

    def start(self) -> None:
        """启动后台采样线程；已在运行或无 psutil 时直接返回。"""
        if self._process is None:
            return

        thread = self._thread
        if thread is not None and thread.is_alive():
            return

        self._thread = None
        self._stop_event.clear()
        self._running = True
        self._last_print_time = time.time()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ResourceMonitor"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止采样并等待线程结束（最长约 2 秒）。"""
        self._running = False
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if thread is None or not thread.is_alive():
            self._thread = None

    def set_print_interval(self, seconds: float) -> None:
        """设置摘要日志间隔（秒），下限 5。

        Args:
            seconds: 目标间隔。
        """
        self.print_interval = max(5.0, seconds)

    def _monitor_loop(self) -> None:
        """监控循环"""
        self._resolve_monitors()

        try:
            if self._process:
                self._process.cpu_percent()

            while self._running and not self._stop_event.is_set():
                self._sample_metrics()
                if self._stop_event.wait(self.sample_interval):
                    return
        except Exception:
            # Sampler thread boundary: never crash the process.
            pass

    def _resolve_monitors(
        self,
    ) -> tuple[PerformanceMonitorPort, HealthMonitorPort]:
        if self._performance_monitor is None:
            from app.ui.performance import perf_monitor
            self._performance_monitor = perf_monitor
        if self._health_monitor is None:
            from app.ui.performance import health_monitor
            self._health_monitor = health_monitor
        return self._performance_monitor, self._health_monitor

    def _sample_metrics(self) -> None:
        """采样一次性能指标"""
        try:
            if self._process is None:
                return
            perf_monitor, health_monitor = self._resolve_monitors()
            memory_mb = self._process.memory_info().rss / 1024 / 1024
            perf_monitor.record("memory_usage", memory_mb, "MB")

            cpu_percent = self._process.cpu_percent()
            perf_monitor.record("cpu_usage", cpu_percent, "%")

            health_monitor.check(cpu_percent, memory_mb)

            now = time.time()
            if (
                self.print_interval > 0
                and (now - self._last_print_time) >= self.print_interval
            ):
                self._last_print_time = now
                self._print_log_summary(perf_monitor)
        except Exception:
            # Metric sampling is best-effort.
            pass

    def _print_log_summary(
        self,
        perf_monitor: PerformanceMonitorPort,
    ) -> None:
        """将性能摘要输出到日志"""
        try:
            from core.logger import logger as _logger
            summary = perf_monitor.summary()
            if not summary:
                return

            lines = ["[性能监控] 周期摘要"]
            for metric_name, stats in summary.items():
                lines.append(
                    f"  {metric_name}: avg={stats['average']:.2f} "
                    f"min={stats['min']:.2f} max={stats['max']:.2f} "
                    f"latest={stats['latest']:.2f} (n={stats['count']})"
                )
            lines.append(f"  memory: {perf_monitor.get_memory_usage():.2f} MB")
            lines.append(f"  cpu: {perf_monitor.get_cpu_percent():.1f}%")
            _logger.info("\n".join(lines), module="PerfMonitor")
        except (OSError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            print(f"[PERF] 资源摘要输出失败: {e}")
        except Exception as e:
            print(f"[PERF] 资源摘要输出失败: {e}")

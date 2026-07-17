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
    def record(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        **metadata: Any,
    ) -> None:
        ...

    def summary(self) -> dict:
        ...

    def get_memory_usage(self) -> float:
        ...

    def get_cpu_percent(self) -> float:
        ...


class HealthMonitorPort(Protocol):
    def check(
        self,
        cpu_percent: float,
        memory_mb: float,
        check_threads: bool = True,
    ) -> None:
        ...


class ResourceUsageMonitor:
    """资源使用监控器

    监控内存、CPU等系统资源使用情况，并可定时输出摘要到日志。
    """

    def __init__(
        self,
        sample_interval: float = 2.0,
        print_interval: float = 120.0,
        *,
        performance_monitor: Optional[PerformanceMonitorPort] = None,
        health_monitor: Optional[HealthMonitorPort] = None,
    ) -> None:
        self.sample_interval = sample_interval
        self.print_interval = print_interval
        self._performance_monitor = performance_monitor
        self._health_monitor = health_monitor
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._process: Any = (
            psutil.Process()
            if _PSUTIL_AVAILABLE and psutil is not None
            else None
        )
        self._last_print_time: float = 0.0
        self._sample_count = 0
        self._thread_check_interval = 10

    def start(self) -> None:
        """开始监控"""
        if self._process is None:
            return

        # 如果已经在运行且线程存活，不重复启动
        if self._running and self._thread and self._thread.is_alive():
            return

        # 如果状态异常（标记为运行但线程不存活），先清理
        if self._running and (not self._thread or not self._thread.is_alive()):
            self._running = False
            self._thread = None

        self._running = True
        self._last_print_time = time.time()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ResourceMonitor"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止监控"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def set_print_interval(self, seconds: float) -> None:
        """设置定时打印间隔（秒）"""
        self.print_interval = max(5.0, seconds)

    def _monitor_loop(self) -> None:
        """监控循环"""
        self._resolve_monitors()

        try:
            if self._process:
                self._process.cpu_percent()

            while self._running:
                self._sample_metrics()
                time.sleep(self.sample_interval)
        except Exception:
            pass

    def _resolve_monitors(
        self,
    ) -> tuple[PerformanceMonitorPort, HealthMonitorPort]:
        if self._performance_monitor is None:
            from app.ui.performance.monitor import PerformanceMonitor
            self._performance_monitor = PerformanceMonitor()
        if self._health_monitor is None:
            from app.ui.performance.health import HealthMonitor
            self._health_monitor = HealthMonitor()
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
        except Exception as e:
            print(f"[PERF] 资源摘要输出失败: {e}")

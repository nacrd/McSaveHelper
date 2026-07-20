"""健康监控与告警模块

检测 UI 卡死、CPU 过载、内存压力、线程阻塞等异常，通过回调发出告警。
"""
import time
import threading
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

from app.ui.performance.thread_monitor import ThreadMonitoringMixin


class AlertLevel(Enum):
    """告警级别"""
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthAlert:
    """健康告警"""
    level: AlertLevel
    category: str      # "cpu" | "memory" | "hang" | "thread_block"
    message: str
    value: float
    threshold: float
    timestamp: float = field(default_factory=time.time)


class HealthMonitor(ThreadMonitoringMixin):
    """健康监控器

    检测 UI 卡死、CPU 过载、内存压力、线程阻塞等异常，通过回调发出告警。
    仅在性能监控启用时生效。
    """

    def __init__(self) -> None:
        # ── 阈值配置 ──
        self.cpu_warning_threshold: float = 90.0
        self.cpu_critical_threshold: float = 98.0
        self.cpu_sustained_samples: int = 12
        self.memory_warning_mb: float = 1024.0
        self.memory_critical_mb: float = 2048.0
        self.hang_timeout: float = 15.0
        self.thread_block_timeout: float = 30.0

        # ── 内部状态 ──
        self._cpu_history: deque = deque(maxlen=60)
        self._memory_history: deque = deque(maxlen=60)
        self._last_heartbeat: float = time.time()
        self._hang_alerted: bool = False
        self._cpu_alerted: bool = False
        self._memory_alerted: bool = False
        self._last_alert_time: Dict[str, float] = {}
        self._alert_cooldown: float = 60.0
        self._lock = threading.Lock()

        # ── 线程监控状态 ──
        self._thread_snapshots: Dict[int, Dict[str, Any]] = {}
        self._blocked_threads: set = set()

        # ── 回调 ──
        self._on_alert: Optional[Callable[[HealthAlert], None]] = None

    def set_alert_callback(
        self,
        callback: Callable[[HealthAlert], None]
    ) -> None:
        """设置告警回调（每次触发告警时调用）"""
        self._on_alert = callback

    def heartbeat(self) -> None:
        """UI 线程心跳，由主循环定期调用。"""
        with self._lock:
            self._last_heartbeat = time.time()
            if self._hang_alerted:
                self._hang_alerted = False

    def check(
        self,
        cpu_percent: float,
        memory_mb: float,
        check_threads: bool = True
    ) -> None:
        """由 ResourceUsageMonitor 采样循环调用，检查各项指标。"""
        now = time.time()

        with self._lock:
            self._cpu_history.append(cpu_percent)
            self._memory_history.append(memory_mb)

        # ── CPU 过载检测 ──
        self._check_cpu(cpu_percent)

        # ── 内存压力检测 ──
        self._check_memory(memory_mb)

        # ── UI 卡死检测 ──
        self._check_hang(now)

        # ── 线程阻塞检测 ──
        if check_threads:
            self._check_thread_blocking(now)

    def _check_cpu(self, cpu_percent: float) -> None:
        """检查 CPU 使用率"""
        history = list(self._cpu_history)
        if len(history) < self.cpu_sustained_samples:
            return

        recent = history[-self.cpu_sustained_samples:]
        avg = sum(recent) / len(recent)

        if avg >= self.cpu_critical_threshold:
            if self._should_alert("cpu_critical"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.CRITICAL,
                    category="cpu",
                    message=(
                        f"CPU 持续过载！近 {self.cpu_sustained_samples} 次"
                        f"平均 {avg:.1f}%（严重阈值 "
                        f"{self.cpu_critical_threshold}%）"
                    ),
                    value=avg,
                    threshold=self.cpu_critical_threshold,
                ))
                self._cpu_alerted = True
        elif avg >= self.cpu_warning_threshold:
            if self._should_alert("cpu_warning"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.WARNING,
                    category="cpu",
                    message=(
                        f"CPU 使用率偏高，近 {self.cpu_sustained_samples} 次"
                        f"平均 {avg:.1f}%（警告阈值 "
                        f"{self.cpu_warning_threshold}%）"
                    ),
                    value=avg,
                    threshold=self.cpu_warning_threshold,
                ))
        else:
            self._cpu_alerted = False

    def _check_memory(self, memory_mb: float) -> None:
        """检查内存使用"""
        if memory_mb >= self.memory_critical_mb:
            if self._should_alert("memory_critical"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.CRITICAL,
                    category="memory",
                    message=(
                        f"内存使用极高：{memory_mb:.0f} MB（严重阈值 "
                        f"{self.memory_critical_mb:.0f} MB）"
                    ),
                    value=memory_mb,
                    threshold=self.memory_critical_mb,
                ))
                self._memory_alerted = True
        elif memory_mb >= self.memory_warning_mb:
            if self._should_alert("memory_warning"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.WARNING,
                    category="memory",
                    message=(
                        f"内存使用偏高：{memory_mb:.0f} MB（警告阈值 "
                        f"{self.memory_warning_mb:.0f} MB）"
                    ),
                    value=memory_mb,
                    threshold=self.memory_warning_mb,
                ))
        else:
            self._memory_alerted = False

    def _check_hang(self, now: float) -> None:
        """检查 UI 卡死"""
        with self._lock:
            elapsed = now - self._last_heartbeat

        if elapsed >= self.hang_timeout:
            if not self._hang_alerted and self._should_alert("hang"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.CRITICAL,
                    category="hang",
                    message=(
                        f"UI 可能已卡死：{elapsed:.0f} 秒无心跳响应"
                        f"（阈值 {self.hang_timeout:.0f}s）"
                    ),
                    value=elapsed,
                    threshold=self.hang_timeout,
                ))
                self._hang_alerted = True
        else:
            self._hang_alerted = False

    def _check_thread_blocking(self, now: float) -> None:
        """检测线程阻塞和死锁"""
        import sys

        try:
            frames = sys._current_frames()
            current_threads = set()

            for thread_id, frame in frames.items():
                current_threads.add(thread_id)
                self._process_thread(thread_id, frame, now)

            self._cleanup_dead_threads(current_threads)
        except Exception:
            # Frame introspection can race under concurrent teardown.
            pass

    def _should_alert(self, key: str) -> bool:
        """检查是否应该发出告警（冷却时间）"""
        now = time.time()
        last = self._last_alert_time.get(key, 0.0)
        if now - last < self._alert_cooldown:
            return False
        self._last_alert_time[key] = now
        return True

    def _fire_alert(self, alert: HealthAlert) -> None:
        """发出告警"""
        try:
            from core.logger import logger as _logger
            _logger.warning(
                f"[健康告警] [{alert.category.upper()}] {alert.message}",
                module="HealthMonitor",
            )
        except Exception:
            print(f"[HealthMonitor] {alert.message}")

        if self._on_alert:
            try:
                self._on_alert(alert)
            except Exception:
                # Alert UI callbacks must not crash the monitor.
                pass

    def get_status(self) -> Dict[str, Any]:
        """返回当前健康状态快照"""
        with self._lock:
            cpu_list = list(self._cpu_history)
            mem_list = list(self._memory_history)
            heartbeat_age = time.time() - self._last_heartbeat
            blocked_count = len(self._blocked_threads)
            total_threads = len(self._thread_snapshots)

        return {
            "cpu_latest": cpu_list[-1] if cpu_list else 0.0,
            "cpu_avg_5": (
                sum(cpu_list[-5:]) / min(5, len(cpu_list))
                if cpu_list else 0.0
            ),
            "memory_latest_mb": mem_list[-1] if mem_list else 0.0,
            "heartbeat_age_s": heartbeat_age,
            "hang_alerted": self._hang_alerted,
            "cpu_alerted": self._cpu_alerted,
            "memory_alerted": self._memory_alerted,
            "blocked_threads": blocked_count,
            "total_threads": total_threads,
        }

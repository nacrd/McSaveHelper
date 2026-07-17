"""性能监控核心模块

提供 PerformanceMonitor 类，负责性能指标的记录、存储和统计。
"""
import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

try:
    import psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False


@dataclass
class PerformanceMetric:
    """性能指标数据"""
    timestamp: datetime
    metric_name: str
    value: float
    unit: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class PerformanceMonitor:
    """性能监控器（单例）

    核心职责：
    - 记录和存储性能指标
    - 提供指标查询和统计
    - 获取系统资源使用情况
    """

    _instance: Optional['PerformanceMonitor'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return

        self._initialized = True
        self.enabled: bool = False
        self.metrics: Dict[str, deque] = {}
        self.max_samples: int = 1000
        self._start_time: float = time.time()
        self._process: Any = (
            psutil.Process()
            if _PSUTIL_AVAILABLE and psutil is not None
            else None
        )
        self._lock = threading.Lock()

    def enable(self) -> None:
        """启用性能监控"""
        self.enabled = True

    def disable(self) -> None:
        """禁用性能监控"""
        self.enabled = False

    def record(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        **metadata: Any,
    ) -> None:
        """记录一条性能指标

        Args:
            metric_name: 指标名称
            value: 指标值
            unit: 单位
            **metadata: 额外元数据
        """
        if not self.enabled:
            return

        metric = PerformanceMetric(
            timestamp=datetime.now(),
            metric_name=metric_name,
            value=value,
            unit=unit,
            metadata=metadata,
        )

        with self._lock:
            if metric_name not in self.metrics:
                self.metrics[metric_name] = deque(maxlen=self.max_samples)
            self.metrics[metric_name].append(metric)

    def get_metrics(self, metric_name: str) -> List[PerformanceMetric]:
        """获取指定指标的所有记录

        Args:
            metric_name: 指标名称

        Returns:
            指标记录列表
        """
        return list(self.metrics.get(metric_name, []))

    def get_average(
        self,
        metric_name: str,
        last_n: Optional[int] = None
    ) -> Optional[float]:
        """获取指标的平均值

        Args:
            metric_name: 指标名称
            last_n: 仅计算最后N个样本

        Returns:
            平均值，如果没有数据则返回 None
        """
        metrics = self.metrics.get(metric_name, [])
        if not metrics:
            return None

        if last_n:
            metrics = list(metrics)[-last_n:]

        return sum(m.value for m in metrics) / len(metrics)

    def get_memory_usage(self) -> float:
        """获取当前内存使用（MB）

        Returns:
            内存使用量（MB），psutil 不可用时返回 0.0
        """
        if self._process is None:
            return 0.0
        return self._process.memory_info().rss / 1024 / 1024

    def get_cpu_percent(self) -> float:
        """获取CPU使用率

        Returns:
            CPU使用率百分比，psutil 不可用时返回 0.0
        """
        if self._process is None:
            return 0.0
        return self._process.cpu_percent(interval=0.1)

    def clear(self) -> None:
        """清除所有指标"""
        self.metrics.clear()

    def summary(self) -> Dict[str, Dict[str, float]]:
        """生成性能摘要

        Returns:
            包含所有指标统计信息的字典
        """
        summary = {}

        for metric_name, metric_list in self.metrics.items():
            if not metric_list:
                continue

            values = [m.value for m in metric_list]
            summary[metric_name] = {
                "count": len(values),
                "average": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "latest": values[-1],
            }

        return summary

    def print_summary(self) -> None:
        """打印性能摘要到控制台"""
        summary = self.summary()

        print("\n" + "=" * 60)
        print("性能监控摘要")
        print("=" * 60)

        for metric_name, stats in summary.items():
            print(f"\n{metric_name}:")
            print(f"  样本数: {stats['count']}")
            print(f"  平均值: {stats['average']:.2f}")
            print(f"  最小值: {stats['min']:.2f}")
            print(f"  最大值: {stats['max']:.2f}")
            print(f"  最新值: {stats['latest']:.2f}")

        print(f"\n内存使用: {self.get_memory_usage():.2f} MB")
        print(f"CPU 使用率: {self.get_cpu_percent():.1f}%")
        print("=" * 60 + "\n")

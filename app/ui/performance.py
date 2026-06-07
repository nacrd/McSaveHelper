"""性能监控工具

提供GUI性能监控和优化工具：
- 帧率监控
- 组件渲染时间跟踪
- 内存使用监控
- 异步操作性能分析
"""
import time
import threading
from typing import Dict, List, Optional, Callable, Any
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
    """性能监控器（单例）"""
    
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
        self._process = psutil.Process() if _PSUTIL_AVAILABLE else None
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
    
    def get_average(self, metric_name: str, last_n: Optional[int] = None) -> Optional[float]:
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
        
        print("\n" + "="*60)
        print("性能监控摘要")
        print("="*60)
        
        for metric_name, stats in summary.items():
            print(f"\n{metric_name}:")
            print(f"  样本数: {stats['count']}")
            print(f"  平均值: {stats['average']:.2f}")
            print(f"  最小值: {stats['min']:.2f}")
            print(f"  最大值: {stats['max']:.2f}")
            print(f"  最新值: {stats['latest']:.2f}")
        
        print(f"\n内存使用: {self.get_memory_usage():.2f} MB")
        print(f"CPU 使用率: {self.get_cpu_percent():.1f}%")
        print("="*60 + "\n")


# 全局性能监控器
perf_monitor = PerformanceMonitor()


class Timer:
    """计时器上下文管理器
    
    用于测量代码块执行时间
    
    Example:
        with Timer("load_data"):
            load_large_dataset()
    """
    
    def __init__(
        self,
        name: str,
        enabled: bool = True,
        auto_record: bool = True,
        callback: Optional[Callable[[str, float], None]] = None
    ):
        self.name = name
        self.enabled = enabled
        self.auto_record = auto_record
        self.callback = callback
        self.start_time: float = 0.0
        self.elapsed: float = 0.0
    
    def __enter__(self):
        if self.enabled:
            self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.enabled:
            self.elapsed = (time.perf_counter() - self.start_time) * 1000  # 转换为毫秒
            
            if self.auto_record:
                perf_monitor.record(self.name, self.elapsed, "ms")
            
            if self.callback:
                self.callback(self.name, self.elapsed)
    
    def __str__(self) -> str:
        return f"{self.name}: {self.elapsed:.2f}ms"


def measure_time(func: Callable) -> Callable:
    """函数执行时间装饰器
    
    Args:
        func: 要测量的函数
        
    Returns:
        包装后的函数
    """
    def wrapper(*args, **kwargs):
        with Timer(func.__name__):
            return func(*args, **kwargs)
    return wrapper


class AsyncOperationTracker:
    """异步操作跟踪器
    
    跟踪后台任务、文件IO等异步操作的性能
    """
    
    def __init__(self):
        self.operations: Dict[str, float] = {}
        self.completed: Dict[str, float] = {}
        self._lock = threading.Lock()
    
    def start(self, operation_id: str) -> None:
        """开始跟踪异步操作
        
        Args:
            operation_id: 操作唯一标识
        """
        with self._lock:
            self.operations[operation_id] = time.time()
    
    def complete(self, operation_id: str) -> Optional[float]:
        """完成异步操作跟踪
        
        Args:
            operation_id: 操作唯一标识
            
        Returns:
            操作耗时（秒），如果操作不存在则返回 None
        """
        with self._lock:
            if operation_id not in self.operations:
                return None
            
            start_time = self.operations.pop(operation_id)
            elapsed = time.time() - start_time
            self.completed[operation_id] = elapsed
            
            # 记录到性能监控器
            perf_monitor.record(
                f"async_operation",
                elapsed * 1000,  # 转换为毫秒
                "ms",
                operation_id=operation_id
            )
            
            return elapsed
    
    def get_pending_operations(self) -> List[str]:
        """获取所有待完成的操作
        
        Returns:
            待完成操作ID列表
        """
        with self._lock:
            return list(self.operations.keys())
    
    def get_operation_time(self, operation_id: str) -> Optional[float]:
        """获取操作的执行时间
        
        Args:
            operation_id: 操作唯一标识
            
        Returns:
            执行时间（秒），如果未完成则返回已用时间
        """
        with self._lock:
            if operation_id in self.completed:
                return self.completed[operation_id]
            elif operation_id in self.operations:
                return time.time() - self.operations[operation_id]
            return None


# 全局异步操作跟踪器
async_tracker = AsyncOperationTracker()


class FrameRateMonitor:
    """帧率监控器
    
    监控UI更新频率
    """
    
    def __init__(self, window_size: int = 60):
        self.frame_times: deque = deque(maxlen=window_size)
        self.last_frame_time: float = time.time()
    
    def tick(self) -> None:
        """记录一次UI更新"""
        current_time = time.time()
        frame_time = current_time - self.last_frame_time
        self.frame_times.append(frame_time)
        self.last_frame_time = current_time
    
    def get_fps(self) -> float:
        """获取当前帧率
        
        Returns:
            FPS值
        """
        if len(self.frame_times) < 2:
            return 0.0
        
        avg_frame_time = sum(self.frame_times) / len(self.frame_times)
        if avg_frame_time == 0:
            return 0.0
        
        return 1.0 / avg_frame_time
    
    def get_average_frame_time(self) -> float:
        """获取平均帧时间（毫秒）
        
        Returns:
            平均帧时间
        """
        if not self.frame_times:
            return 0.0
        
        return (sum(self.frame_times) / len(self.frame_times)) * 1000


def log_slow_operation(threshold_ms: float = 100):
    """慢操作日志装饰器
    
    如果操作超过阈值，自动记录日志
    
    Args:
        threshold_ms: 阈值（毫秒）
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            
            if elapsed > threshold_ms:
                print(f"[PERF WARNING] {func.__name__} 执行缓慢: {elapsed:.2f}ms (阈值: {threshold_ms}ms)")
                perf_monitor.record(f"slow_operation_{func.__name__}", elapsed, "ms")
            
            return result
        return wrapper
    return decorator


class ResourceUsageMonitor:
    """资源使用监控器
    
    监控内存、CPU等系统资源使用情况
    """
    
    def __init__(self, sample_interval: float = 1.0):
        self.sample_interval = sample_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._process = psutil.Process() if _PSUTIL_AVAILABLE else None
    
    def start(self) -> None:
        """开始监控"""
        if self._running or self._process is None:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
    
    def _monitor_loop(self) -> None:
        """监控循环"""
        while self._running:
            try:
                # 记录内存使用
                memory_mb = self._process.memory_info().rss / 1024 / 1024
                perf_monitor.record("memory_usage", memory_mb, "MB")
                
                # 记录CPU使用率
                cpu_percent = self._process.cpu_percent(interval=self.sample_interval)
                perf_monitor.record("cpu_usage", cpu_percent, "%")
                
            except Exception as e:
                print(f"[ERROR] 资源监控失败: {e}")
            
            time.sleep(self.sample_interval)


# 全局资源使用监控器
resource_monitor = ResourceUsageMonitor()

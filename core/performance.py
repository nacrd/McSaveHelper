"""性能监控工具

提供迁移操作的性能追踪、内存监控和统计功能。
"""
import time
import tracemalloc
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from contextlib import contextmanager
import logging


logger = logging.getLogger(__name__)


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
    
    @property
    def throughput_files_per_sec(self) -> float:
        """计算文件处理吞吐量"""
        if self.duration_seconds > 0 and self.files_processed > 0:
            return self.files_processed / self.duration_seconds
        return 0.0
    
    @property
    def throughput_mb_per_sec(self) -> float:
        """计算字节处理吞吐量（MB/s）"""
        if self.duration_seconds > 0 and self.bytes_processed > 0:
            return (self.bytes_processed / (1024 * 1024)) / self.duration_seconds
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "operation": self.operation,
            "duration_seconds": round(self.duration_seconds, 3),
            "memory_peak_mb": round(self.memory_peak_mb, 2),
            "memory_delta_mb": round(self.memory_delta_mb, 2),
            "files_processed": self.files_processed,
            "bytes_processed": self.bytes_processed,
            "errors": self.errors,
            "throughput_files_per_sec": round(self.throughput_files_per_sec, 2),
            "throughput_mb_per_sec": round(self.throughput_mb_per_sec, 2),
            "metadata": self.metadata
        }
    
    def __str__(self) -> str:
        """格式化输出性能指标"""
        lines = [
            f"=== 性能指标: {self.operation} ===",
            f"耗时: {self.duration_seconds:.3f}秒",
            f"内存峰值: {self.memory_peak_mb:.2f}MB",
            f"内存增量: {self.memory_delta_mb:.2f}MB",
            f"处理文件: {self.files_processed}个",
            f"处理数据: {self.bytes_processed / (1024*1024):.2f}MB",
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


class PerformanceMonitor:
    """性能监控器
    
    用于追踪操作的执行时间和内存使用情况。
    
    示例:
        >>> monitor = PerformanceMonitor()
        >>> with monitor.track("文件扫描"):
        ...     # 执行操作
        ...     monitor.increment_files(10)
        ...     monitor.increment_bytes(1024 * 1024)
        >>> print(monitor.get_metrics("文件扫描"))
    """
    
    def __init__(self) -> None:
        """初始化性能监控器"""
        self._metrics: Dict[str, PerformanceMetrics] = {}
        self._current_operation: Optional[str] = None
        self._start_time: float = 0.0
        self._start_memory: float = 0.0
        self._memory_tracking: bool = False
        
    def start_tracking_memory(self) -> None:
        """开始内存追踪"""
        if not self._memory_tracking:
            tracemalloc.start()
            self._memory_tracking = True
    
    def stop_tracking_memory(self) -> None:
        """停止内存追踪"""
        if self._memory_tracking:
            tracemalloc.stop()
            self._memory_tracking = False
    
    @contextmanager
    def track(self, operation: str, metadata: Optional[Dict[str, Any]] = None):
        """追踪操作的性能指标
        
        Args:
            operation: 操作名称
            metadata: 额外的元数据
        
        示例:
            >>> with monitor.track("UUID 迁移", {"mode": "fast"}):
            ...     migrate_fast(world_path, mapping)
        """
        self._current_operation = operation
        self._start_time = time.perf_counter()
        
        # 启动内存追踪
        memory_tracking_started = False
        if not self._memory_tracking:
            self.start_tracking_memory()
            memory_tracking_started = True
        
        # 记录起始内存
        if self._memory_tracking:
            current, peak = tracemalloc.get_traced_memory()
            self._start_memory = current / (1024 * 1024)  # 转换为 MB
        else:
            self._start_memory = 0.0
        
        # 初始化指标
        self._metrics[operation] = PerformanceMetrics(
            operation=operation,
            duration_seconds=0.0,
            memory_peak_mb=0.0,
            memory_delta_mb=0.0,
            metadata=metadata or {}
        )
        
        try:
            yield self
        finally:
            # 计算耗时
            duration = time.perf_counter() - self._start_time
            
            # 计算内存使用
            memory_delta = 0.0
            memory_peak = 0.0
            if self._memory_tracking:
                current, peak = tracemalloc.get_traced_memory()
                memory_delta = (current / (1024 * 1024)) - self._start_memory
                memory_peak = peak / (1024 * 1024)
            
            # 更新指标
            metrics = self._metrics[operation]
            metrics.duration_seconds = duration
            metrics.memory_peak_mb = memory_peak
            metrics.memory_delta_mb = memory_delta
            
            # 记录日志
            logger.info(f"操作 '{operation}' 完成: 耗时 {duration:.3f}秒, "
                       f"内存峰值 {memory_peak:.2f}MB, 内存增量 {memory_delta:.2f}MB")
            
            # 如果是我们启动的内存追踪，则停止它
            if memory_tracking_started:
                self.stop_tracking_memory()
            
            self._current_operation = None
    
    def increment_files(self, count: int = 1) -> None:
        """增加处理的文件计数"""
        if self._current_operation and self._current_operation in self._metrics:
            self._metrics[self._current_operation].files_processed += count
    
    def increment_bytes(self, bytes_count: int) -> None:
        """增加处理的字节数"""
        if self._current_operation and self._current_operation in self._metrics:
            self._metrics[self._current_operation].bytes_processed += bytes_count
    
    def increment_errors(self, count: int = 1) -> None:
        """增加错误计数"""
        if self._current_operation and self._current_operation in self._metrics:
            self._metrics[self._current_operation].errors += count
    
    def add_metadata(self, key: str, value: Any) -> None:
        """添加元数据到当前操作"""
        if self._current_operation and self._current_operation in self._metrics:
            self._metrics[self._current_operation].metadata[key] = value
    
    def get_metrics(self, operation: str) -> Optional[PerformanceMetrics]:
        """获取指定操作的性能指标"""
        return self._metrics.get(operation)
    
    def get_all_metrics(self) -> Dict[str, PerformanceMetrics]:
        """获取所有操作的性能指标"""
        return self._metrics.copy()
    
    def clear(self) -> None:
        """清除所有性能指标"""
        self._metrics.clear()
    
    def print_summary(self) -> None:
        """打印所有操作的性能摘要"""
        if not self._metrics:
            print("没有性能数据")
            return
        
        print("\n" + "=" * 60)
        print("性能监控摘要")
        print("=" * 60)
        
        for operation, metrics in self._metrics.items():
            print(f"\n{metrics}")
        
        # 总计
        total_duration = sum(m.duration_seconds for m in self._metrics.values())
        total_files = sum(m.files_processed for m in self._metrics.values())
        total_bytes = sum(m.bytes_processed for m in self._metrics.values())
        total_errors = sum(m.errors for m in self._metrics.values())
        
        print("\n" + "-" * 60)
        print(f"总耗时: {total_duration:.3f}秒")
        print(f"总文件数: {total_files}")
        print(f"总数据量: {total_bytes / (1024*1024):.2f}MB")
        if total_errors > 0:
            print(f"总错误数: {total_errors}")
        print("=" * 60 + "\n")


def profile_function(operation_name: Optional[str] = None) -> Callable:
    """函数性能分析装饰器
    
    Args:
        operation_name: 操作名称，默认使用函数名
    
    示例:
        >>> @profile_function("UUID 迁移")
        ... def migrate(world_path):
        ...     pass
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            name = operation_name or func.__name__
            monitor = PerformanceMonitor()
            
            with monitor.track(name):
                result = func(*args, **kwargs)
            
            # 打印性能指标
            metrics = monitor.get_metrics(name)
            if metrics:
                logger.info(str(metrics))
            
            return result
        
        return wrapper
    return decorator


import threading

# 全局监控器实例（可选）
_global_monitor: Optional[PerformanceMonitor] = None
_global_monitor_lock = threading.Lock()


def get_global_monitor() -> PerformanceMonitor:
    """获取全局性能监控器实例（线程安全）"""
    global _global_monitor
    with _global_monitor_lock:
        if _global_monitor is None:
            _global_monitor = PerformanceMonitor()
    return _global_monitor


def reset_global_monitor() -> None:
    """重置全局性能监控器"""
    global _global_monitor
    if _global_monitor:
        _global_monitor.clear()
        _global_monitor.stop_tracking_memory()
    _global_monitor = None

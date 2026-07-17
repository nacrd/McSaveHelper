"""计时器和异步操作跟踪模块

提供 Timer 上下文管理器和 AsyncOperationTracker 用于跟踪操作性能。
"""
import time
import threading
from typing import Dict, List, Optional, Callable


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
            # 转换为毫秒
            self.elapsed = (time.perf_counter() - self.start_time) * 1000

            if self.auto_record:
                # 延迟导入，避免循环依赖
                from app.ui.performance import perf_monitor
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
                print(
                    f"[PERF WARNING] {func.__name__} 执行缓慢: "
                    f"{elapsed:.2f}ms (阈值: {threshold_ms}ms)"
                )
                # 延迟导入，避免循环依赖
                from app.ui.performance import perf_monitor
                perf_monitor.record(
                    f"slow_operation_{func.__name__}",
                    elapsed,
                    "ms"
                )

            return result
        return wrapper
    return decorator


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
            from app.ui.performance import perf_monitor
            perf_monitor.record(
                "async_operation",
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

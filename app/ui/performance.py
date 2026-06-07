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
from enum import Enum

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
    
    监控内存、CPU等系统资源使用情况，并可定时输出摘要到日志。
    """
    
    def __init__(self, sample_interval: float = 1.0, print_interval: float = 60.0):
        self.sample_interval = sample_interval
        self.print_interval = print_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._process = psutil.Process() if _PSUTIL_AVAILABLE else None
        self._last_print_time: float = 0.0
    
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
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
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
        while self._running:
            try:
                # 记录内存使用
                memory_mb = self._process.memory_info().rss / 1024 / 1024
                perf_monitor.record("memory_usage", memory_mb, "MB")
                
                # 记录CPU使用率
                cpu_percent = self._process.cpu_percent(interval=self.sample_interval)
                perf_monitor.record("cpu_usage", cpu_percent, "%")
                
                # 健康检查（CPU 过载 / 内存压力 / UI 卡死）
                health_monitor.check(cpu_percent, memory_mb)

                # 定时打印摘要
                now = time.time()
                if self.print_interval > 0 and (now - self._last_print_time) >= self.print_interval:
                    self._last_print_time = now
                    self._print_log_summary()
                
            except Exception as e:
                print(f"[ERROR] 资源监控失败: {e}")
            
            time.sleep(self.sample_interval)
    
    def _print_log_summary(self) -> None:
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


# 全局资源使用监控器
resource_monitor = ResourceUsageMonitor()


class AlertLevel(Enum):
    """告警级别"""
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthAlert:
    """健康告警"""
    level: AlertLevel
    category: str      # "cpu" | "memory" | "hang"
    message: str
    value: float
    threshold: float
    timestamp: float = field(default_factory=time.time)


class HealthMonitor:
    """健康监控器

    检测 UI 卡死、CPU 过载、内存压力、线程阻塞等异常，通过回调发出告警。
    仅在性能监控启用时生效。
    """

    def __init__(self) -> None:
        # ── 阈值配置 ──
        self.cpu_warning_threshold: float = 85.0      # CPU 连续高于此值触发警告
        self.cpu_critical_threshold: float = 95.0     # CPU 连续高于此值触发严重告警
        self.cpu_sustained_samples: int = 5           # 连续采样次数
        self.memory_warning_mb: float = 1024.0        # 内存警告阈值（MB）
        self.memory_critical_mb: float = 2048.0       # 内存严重告警阈值（MB）
        self.hang_timeout: float = 15.0               # UI 心跳超时（秒）
        self.thread_block_timeout: float = 30.0       # 线程阻塞超时（秒）

        # ── 内部状态 ──
        self._cpu_history: deque = deque(maxlen=60)   # 最近 60 次 CPU 采样
        self._memory_history: deque = deque(maxlen=60)
        self._last_heartbeat: float = time.time()
        self._hang_alerted: bool = False
        self._cpu_alerted: bool = False
        self._memory_alerted: bool = False
        self._last_alert_time: Dict[str, float] = {}
        self._alert_cooldown: float = 60.0            # 同类告警冷却（秒）
        self._lock = threading.Lock()

        # ── 线程监控状态 ──
        self._thread_snapshots: Dict[int, Dict[str, Any]] = {}  # thread_id -> {location, timestamp, alerted}
        self._blocked_threads: set = set()

        # ── 回调 ──
        self._on_alert: Optional[Callable[[HealthAlert], None]] = None

    def set_alert_callback(self, callback: Callable[[HealthAlert], None]) -> None:
        """设置告警回调（每次触发告警时调用）"""
        self._on_alert = callback

    def heartbeat(self) -> None:
        """UI 线程心跳，由主循环定期调用。"""
        with self._lock:
            self._last_heartbeat = time.time()
            if self._hang_alerted:
                self._hang_alerted = False

    def check(self, cpu_percent: float, memory_mb: float) -> None:
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
        self._check_thread_blocking(now)

    def _check_cpu(self, cpu_percent: float) -> None:
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
                    message=f"CPU 持续过载！近 {self.cpu_sustained_samples} 次平均 {avg:.1f}%（严重阈值 {self.cpu_critical_threshold}%）",
                    value=avg,
                    threshold=self.cpu_critical_threshold,
                ))
                self._cpu_alerted = True
        elif avg >= self.cpu_warning_threshold:
            if self._should_alert("cpu_warning"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.WARNING,
                    category="cpu",
                    message=f"CPU 使用率偏高，近 {self.cpu_sustained_samples} 次平均 {avg:.1f}%（警告阈值 {self.cpu_warning_threshold}%）",
                    value=avg,
                    threshold=self.cpu_warning_threshold,
                ))
        else:
            self._cpu_alerted = False

    def _check_memory(self, memory_mb: float) -> None:
        if memory_mb >= self.memory_critical_mb:
            if self._should_alert("memory_critical"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.CRITICAL,
                    category="memory",
                    message=f"内存使用极高：{memory_mb:.0f} MB（严重阈值 {self.memory_critical_mb:.0f} MB）",
                    value=memory_mb,
                    threshold=self.memory_critical_mb,
                ))
                self._memory_alerted = True
        elif memory_mb >= self.memory_warning_mb:
            if self._should_alert("memory_warning"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.WARNING,
                    category="memory",
                    message=f"内存使用偏高：{memory_mb:.0f} MB（警告阈值 {self.memory_warning_mb:.0f} MB）",
                    value=memory_mb,
                    threshold=self.memory_warning_mb,
                ))
        else:
            self._memory_alerted = False

    def _check_hang(self, now: float) -> None:
        with self._lock:
            elapsed = now - self._last_heartbeat

        if elapsed >= self.hang_timeout:
            if not self._hang_alerted and self._should_alert("hang"):
                self._fire_alert(HealthAlert(
                    level=AlertLevel.CRITICAL,
                    category="hang",
                    message=f"UI 可能已卡死：{elapsed:.0f} 秒无心跳响应（阈值 {self.hang_timeout:.0f}s）",
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
            # 获取所有线程的当前堆栈帧
            frames = sys._current_frames()
            current_threads = set()
            
            for thread_id, frame in frames.items():
                current_threads.add(thread_id)
                
                # 提取线程位置指纹：文件名:行号:函数名
                location = f"{frame.f_code.co_filename}:{frame.f_lineno}:{frame.f_code.co_name}"
                
                # 检查是否为良性等待（time.sleep, threading.Event.wait 等）
                is_benign_wait = self._is_benign_wait(frame)
                
                # 如果是新线程或位置变化，更新快照
                if thread_id not in self._thread_snapshots:
                    self._thread_snapshots[thread_id] = {
                        "location": location,
                        "timestamp": now,
                        "alerted": False,
                        "name": self._get_thread_name(thread_id),
                        "benign": is_benign_wait,
                    }
                else:
                    snapshot = self._thread_snapshots[thread_id]
                    
                    # 位置变化，说明线程还在活动
                    if snapshot["location"] != location:
                        snapshot["location"] = location
                        snapshot["timestamp"] = now
                        snapshot["alerted"] = False
                        snapshot["benign"] = is_benign_wait
                        if thread_id in self._blocked_threads:
                            self._blocked_threads.remove(thread_id)
                    else:
                        # 位置未变，检查是否超时
                        elapsed = now - snapshot["timestamp"]
                        
                        # 良性等待的超时阈值更宽松
                        threshold = self.thread_block_timeout * 2 if is_benign_wait else self.thread_block_timeout
                        
                        if elapsed >= threshold:
                            if not snapshot["alerted"] and self._should_alert(f"thread_block_{thread_id}"):
                                # 提取堆栈信息
                                stack_lines = []
                                f = frame
                                depth = 0
                                while f is not None and depth < 5:
                                    stack_lines.append(f"  {f.f_code.co_filename}:{f.f_lineno} in {f.f_code.co_name}")
                                    f = f.f_back
                                    depth += 1
                                
                                stack_info = "\n".join(stack_lines) if stack_lines else location
                                thread_name = snapshot.get("name", f"Thread-{thread_id}")
                                
                                # 良性等待降级为警告
                                level = AlertLevel.WARNING if is_benign_wait else AlertLevel.CRITICAL
                                
                                self._fire_alert(HealthAlert(
                                    level=level,
                                    category="thread_block",
                                    message=f"线程 {thread_name} 可能阻塞：{elapsed:.0f}s 无进展（阈值 {threshold:.0f}s）\n堆栈:\n{stack_info}",
                                    value=elapsed,
                                    threshold=threshold,
                                ))
                                
                                snapshot["alerted"] = True
                                self._blocked_threads.add(thread_id)
            
            # 清理已退出的线程
            dead_threads = set(self._thread_snapshots.keys()) - current_threads
            for thread_id in dead_threads:
                self._thread_snapshots.pop(thread_id, None)
                self._blocked_threads.discard(thread_id)
                
        except Exception:
            pass  # 线程检测失败不影响其他监控

    def _get_thread_name(self, thread_id: int) -> str:
        """获取线程名称"""
        try:
            for thread in threading.enumerate():
                if thread.ident == thread_id:
                    return thread.name
        except Exception:
            pass
        return f"Thread-{thread_id}"

    def _is_benign_wait(self, frame) -> bool:
        """判断是否为良性等待（time.sleep, Event.wait 等）"""
        try:
            # 检查堆栈中是否包含已知的等待函数
            f = frame
            depth = 0
            while f is not None and depth < 10:
                func_name = f.f_code.co_name
                file_name = f.f_code.co_filename
                
                # 常见的良性等待模式
                if func_name in ('sleep', 'wait', 'join', 'select', 'poll', 'recv', 'accept'):
                    return True
                
                # threading 模块的等待
                if 'threading.py' in file_name and func_name in ('wait', '_wait'):
                    return True
                
                # queue 模块的阻塞获取
                if 'queue.py' in file_name and func_name in ('get', 'put'):
                    return True
                
                f = f.f_back
                depth += 1
        except Exception:
            pass
        
        return False

    def _should_alert(self, key: str) -> bool:
        now = time.time()
        last = self._last_alert_time.get(key, 0.0)
        if now - last < self._alert_cooldown:
            return False
        self._last_alert_time[key] = now
        return True

    def _fire_alert(self, alert: HealthAlert) -> None:
        try:
            from core.logger import logger as _logger
            lvl = "WARNING" if alert.level == AlertLevel.WARNING else "ERROR"
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
            "cpu_avg_5": (sum(cpu_list[-5:]) / min(5, len(cpu_list))) if cpu_list else 0.0,
            "memory_latest_mb": mem_list[-1] if mem_list else 0.0,
            "heartbeat_age_s": heartbeat_age,
            "hang_alerted": self._hang_alerted,
            "cpu_alerted": self._cpu_alerted,
            "memory_alerted": self._memory_alerted,
            "blocked_threads": blocked_count,
            "total_threads": total_threads,
        }


# 全局健康监控器
health_monitor = HealthMonitor()

"""Central log manager with async queue processing."""
import sys
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from queue import Queue, Empty

from .models import LogLevel, LogRecord
from .handlers import LogHandler


class LogManager:
    """中心化日志管理器（进程级单例）。

    所有 ``log``/级别便捷方法只入队，由后台 daemon 线程异步分发到
    handlers，避免业务线程被 I/O 阻塞。Worker 边界吞掉 handler 异常，
    保证日志失败不会拖垮主进程。
    """

    _instance: Optional['LogManager'] = None
    _lock = threading.Lock()
    _STOP = object()

    def __new__(cls) -> 'LogManager':
        """返回进程级唯一实例（线程安全）。"""
        # 双重检查式单例：多线程首次 import 时仍只创建一个实例。
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        """初始化队列、模块级别表并启动后台 worker（仅首次生效）。"""
        if getattr(self, '_initialized', False):
            return
        self.handlers: List[LogHandler] = []
        self.min_level: LogLevel = LogLevel.INFO
        self._queue: Queue = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._module_levels: Dict[str, LogLevel] = {}
        self._start_worker()
        self._initialized = True

    def _start_worker(self) -> None:
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            name="LogManager-Worker",
            daemon=True,
        )
        self._worker_thread.start()

    def _process_queue(self) -> None:
        while True:
            try:
                record = self._queue.get(timeout=0.1)
                try:
                    if record is self._STOP:
                        return
                    self._dispatch(record)
                finally:
                    self._queue.task_done()
            except Empty:
                continue
            except Exception as exc:
                # Worker boundary: logging must not crash the process.
                print(f"日志处理器异常: {exc}", file=sys.stderr)

    def _dispatch(self, record: LogRecord) -> None:
        module_level = self._module_levels.get(record.module)
        if module_level and record.level < module_level:
            return
        if record.level < self.min_level:
            return
        for handler in self.handlers:
            try:
                handler.handle(record)
            except Exception as exc:
                print(
                    f"日志处理器 {handler.__class__.__name__} 失败: {exc}",
                    file=sys.stderr,
                )

    def add_handler(self, handler: LogHandler) -> None:
        """注册日志输出处理器。

        Args:
            handler: 实现 ``handle`` 的处理器实例。
        """
        self.handlers.append(handler)

    def remove_handler(self, handler: LogHandler) -> None:
        """移除并关闭指定处理器。

        Args:
            handler: 已注册的处理器；不在列表中时静默忽略。
        """
        if handler in self.handlers:
            self.handlers.remove(handler)
            handler.close()

    def set_level(self, level: LogLevel) -> None:
        """设置全局最低输出级别。

        Args:
            level: 低于该级别的记录在分发前被丢弃。
        """
        self.min_level = level

    def set_module_level(self, module: str, level: LogLevel) -> None:
        """为指定 ``module`` 标签设置独立最低级别。

        模块级阈值优先于全局级别，便于单独打开某子系统的 DEBUG。

        Args:
            module: 与 ``log(..., module=...)`` 对应的模块名。
            level: 该模块的最低输出级别。
        """
        self._module_levels[module] = level

    def log(self, level: LogLevel, message: str, module: str = "",
            extra: Optional[Dict[str, Any]] = None) -> None:
        """构造 ``LogRecord`` 并异步入队。

        Args:
            level: 日志级别。
            message: 日志正文。
            module: 可选模块标签，用于过滤与格式化。
            extra: 可选结构化附加字段。
        """
        current_thread = threading.current_thread()
        record = LogRecord(
            timestamp=datetime.now(), level=level, message=message, module=module,
            thread_id=current_thread.ident or 0, thread_name=current_thread.name,
            extra=extra or {}
        )
        self._queue.put(record)

    def debug(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 DEBUG 级别日志。

        Args:
            message: 日志正文。
            module: 可选模块标签。
            extra: 可选附加字段。
        """
        self.log(LogLevel.DEBUG, message, module, extra)

    def info(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 INFO 级别日志。

        Args:
            message: 日志正文。
            module: 可选模块标签。
            extra: 可选附加字段。
        """
        self.log(LogLevel.INFO, message, module, extra)

    def success(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 SUCCESS 级别日志（业务成功语义）。

        Args:
            message: 日志正文。
            module: 可选模块标签。
            extra: 可选附加字段。
        """
        self.log(LogLevel.SUCCESS, message, module, extra)

    def api(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 API 级别日志（外部接口调用轨迹）。

        Args:
            message: 日志正文。
            module: 可选模块标签。
            extra: 可选附加字段。
        """
        self.log(LogLevel.API, message, module, extra)

    def warning(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 WARNING 级别日志。

        Args:
            message: 日志正文。
            module: 可选模块标签。
            extra: 可选附加字段。
        """
        self.log(LogLevel.WARNING, message, module, extra)

    def error(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 ERROR 级别日志。

        Args:
            message: 日志正文。
            module: 可选模块标签。
            extra: 可选附加字段。
        """
        self.log(LogLevel.ERROR, message, module, extra)

    def critical(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 CRITICAL 级别日志。

        Args:
            message: 日志正文。
            module: 可选模块标签。
            extra: 可选附加字段。
        """
        self.log(LogLevel.CRITICAL, message, module, extra)

    def flush(self) -> None:
        """尽力刷新所有 handler 缓冲区；关闭路径失败时忽略。"""
        for handler in self.handlers:
            try:
                handler.flush()
            except (OSError, IOError, RuntimeError, ValueError):
                # Best-effort flush on shutdown/teardown.
                pass

    def close(self) -> None:
        """停止 worker、刷新并关闭全部 handler，清空注册表。"""
        self._running = False
        self._queue.put(self._STOP)
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2.0)
        self.flush()
        for handler in self.handlers:
            try:
                handler.close()
            except (OSError, IOError, RuntimeError, ValueError):
                # Best-effort close; handlers may already be torn down.
                pass
        self.handlers.clear()

    def shutdown(self) -> None:
        """``close`` 的别名，供进程退出钩子统一调用。"""
        self.close()

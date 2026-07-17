"""Central log manager with async queue processing."""
import sys
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from queue import Queue, Empty

from .models import LogLevel, LogRecord
from .handlers import LogHandler


class LogManager:
    """中心化日志管理器（单例模式）"""

    _instance: Optional['LogManager'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'LogManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
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
        while self._running:
            try:
                record = self._queue.get(timeout=0.1)
                self._dispatch(record)
                self._queue.task_done()
            except Empty:
                continue
            except Exception as e:
                print(f"日志处理器异常: {e}", file=sys.stderr)

    def _dispatch(self, record: LogRecord) -> None:
        module_level = self._module_levels.get(record.module)
        if module_level and record.level < module_level:
            return
        if record.level < self.min_level:
            return
        for handler in self.handlers:
            try:
                handler.handle(record)
            except Exception as e:
                print(f"日志处理器 {handler.__class__.__name__} 失败: {e}", file=sys.stderr)

    def add_handler(self, handler: LogHandler) -> None:
        self.handlers.append(handler)

    def remove_handler(self, handler: LogHandler) -> None:
        if handler in self.handlers:
            self.handlers.remove(handler)
            handler.close()

    def set_level(self, level: LogLevel) -> None:
        self.min_level = level

    def set_module_level(self, module: str, level: LogLevel) -> None:
        self._module_levels[module] = level

    def log(self, level: LogLevel, message: str, module: str = "",
            extra: Optional[Dict[str, Any]] = None) -> None:
        current_thread = threading.current_thread()
        record = LogRecord(
            timestamp=datetime.now(), level=level, message=message, module=module,
            thread_id=current_thread.ident or 0, thread_name=current_thread.name,
            extra=extra or {}
        )
        self._queue.put(record)

    def debug(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.DEBUG, message, module, extra)

    def info(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.INFO, message, module, extra)

    def success(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.log(LogLevel.SUCCESS, message, module, extra)

    def api(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.API, message, module, extra)

    def warning(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.log(LogLevel.WARNING, message, module, extra)

    def error(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.ERROR, message, module, extra)

    def critical(
        self,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.log(LogLevel.CRITICAL, message, module, extra)

    def flush(self) -> None:
        for handler in self.handlers:
            try:
                handler.flush()
            except Exception:
                pass

    def shutdown(self) -> None:
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
        for handler in self.handlers:
            try:
                handler.close()
            except Exception:
                pass
        self.handlers.clear()

"""Central logging manager and the standard-library logging bridge."""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from collections.abc import Mapping
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional

from .handlers import LogHandler
from .models import LogLevel, LogRecord

logging.addLevelName(LogLevel.API.value, "API")
logging.addLevelName(LogLevel.SUCCESS.value, "SUCCESS")


class _ForwardingHandler(logging.Handler):
    """Forward a stdlib record without performing application I/O."""

    def __init__(self, callback: Callable[[logging.LogRecord], None]) -> None:
        super().__init__(level=logging.NOTSET)
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(record)
        except (RuntimeError, TypeError, ValueError):
            # Logging must never make the caller fail.
            pass


class LogManager:
    """异步日志管理器，并兼容 Python 标准库 ``logging``。

    门面方法首先调用标准库 logger，再由内部入队处理器转换成项目的
    :class:`LogRecord`。外部命名 logger 可通过 ``install_stdlib_bridge``
    进入同一队列；原有自定义 handler 契约保持不变。
    """

    _instance: Optional["LogManager"] = None
    _lock = threading.Lock()
    _STOP = object()

    def __new__(cls) -> "LogManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.handlers: List[LogHandler] = []
        self.min_level = LogLevel.INFO
        self._queue: Queue[object] = Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._module_levels: Dict[str, LogLevel] = {}
        self._handlers_lock = threading.RLock()
        self._stdlib_logger = logging.getLogger("mcsavehelper")
        self._stdlib_logger.setLevel(logging.DEBUG)
        self._stdlib_logger.propagate = False
        self._ingress_handler = _ForwardingHandler(self._enqueue_stdlib_record)
        self._stdlib_logger.addHandler(self._ingress_handler)
        self._stdlib_bridge: Optional[_ForwardingHandler] = None
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

    def install_stdlib_bridge(self) -> None:
        """将 root logger 的记录接入本地异步管线。"""
        root_logger = logging.getLogger()
        if self._stdlib_bridge is None:
            self._stdlib_bridge = _ForwardingHandler(self._enqueue_stdlib_record)
            root_logger.addHandler(self._stdlib_bridge)
        root_logger.setLevel(min(root_logger.level or logging.WARNING, logging.DEBUG))

    def remove_stdlib_bridge(self) -> None:
        """移除 root logger 桥接，供测试和关闭路径使用。"""
        if self._stdlib_bridge is None:
            return
        logging.getLogger().removeHandler(self._stdlib_bridge)
        self._stdlib_bridge.close()
        self._stdlib_bridge = None

    def _write_internal_error(self, message: str) -> None:
        try:
            print(message, file=sys.__stderr__)
        except (OSError, ValueError):
            pass

    def _process_queue(self) -> None:
        while True:
            try:
                record = self._queue.get(timeout=0.1)
                try:
                    if record is self._STOP:
                        return
                    if isinstance(record, LogRecord):
                        self._dispatch(record)
                finally:
                    self._queue.task_done()
            except Empty:
                continue
            except Exception as exc:  # worker boundary must stay alive
                self._write_internal_error(f"日志处理器异常: {exc}")

    def _dispatch(self, record: LogRecord) -> None:
        module_level = self._module_levels.get(record.module)
        if module_level is not None and record.level < module_level:
            return
        if record.level < self.min_level:
            return
        with self._handlers_lock:
            handlers = tuple(self.handlers)
        for handler in handlers:
            try:
                handler.handle(record)
            except Exception as exc:  # handler failure must not affect the app
                self._write_internal_error(
                    f"日志处理器 {handler.__class__.__name__} 失败: {exc}"
                )

    def _enqueue_stdlib_record(self, record: logging.LogRecord) -> None:
        if not self._running:
            return
        self._queue.put(self._convert_stdlib_record(record))

    @staticmethod
    def _record_timestamp(record: logging.LogRecord) -> datetime:
        return datetime.fromtimestamp(record.created).astimezone()

    @staticmethod
    def _record_exception(
        record: logging.LogRecord,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not record.exc_info or record.exc_info[0] is None:
            return None, None, None
        exc_type, exc_value, _ = record.exc_info
        stack = record.exc_text or "".join(traceback.format_exception(*record.exc_info))
        return exc_type.__name__, str(exc_value), stack

    @staticmethod
    def _record_extra(record: logging.LogRecord) -> Dict[str, Any]:
        supplied = getattr(record, "_mc_extra", {})
        extra: Dict[str, Any] = dict(supplied) if isinstance(supplied, Mapping) else {}
        reserved = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
        for key, value in record.__dict__.items():
            if key not in reserved and not key.startswith("_mc_"):
                extra.setdefault(key, value)
        return extra

    def _convert_stdlib_record(self, record: logging.LogRecord) -> LogRecord:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        module = getattr(record, "_mc_module", "")
        if not module:
            module = record.name
        exception_type, exception_message, stack_trace = self._record_exception(record)
        return LogRecord(
            timestamp=self._record_timestamp(record),
            level=self._level_from_stdlib(record),
            message=message,
            module=str(module),
            thread_id=record.thread or 0,
            thread_name=record.threadName or "",
            extra=self._record_extra(record),
            process_id=record.process or os.getpid(),
            logger_name=record.name,
            exception_type=exception_type,
            exception_message=exception_message,
            stack_trace=stack_trace,
            created_at=datetime.now().astimezone(),
        )

    @staticmethod
    def _level_from_stdlib(record: logging.LogRecord) -> LogLevel:
        for level in LogLevel:
            if level.value == record.levelno:
                return level
        return LogLevel.from_string(record.levelname)

    def add_handler(self, handler: LogHandler) -> None:
        """注册一个自定义输出 handler。"""
        with self._handlers_lock:
            if handler not in self.handlers:
                self.handlers.append(handler)

    def remove_handler(self, handler: LogHandler) -> None:
        """移除并关闭指定 handler；未注册时忽略。"""
        removed = False
        with self._handlers_lock:
            if handler in self.handlers:
                self.handlers.remove(handler)
                removed = True
        if removed:
            handler.close()

    def set_level(self, level: LogLevel) -> None:
        self.min_level = level

    def set_module_level(self, module: str, level: LogLevel) -> None:
        self._module_levels[module] = level

    def log(
        self,
        level: LogLevel,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None,
        exc_info: Optional[bool] = None,
        stack_info: bool = False,
    ) -> None:
        """通过标准库 logger 异步记录结构化消息。"""
        self._stdlib_logger.log(
            level.value,
            message,
            extra={"_mc_module": module, "_mc_extra": dict(extra or {})},
            exc_info=exc_info,
            stack_info=stack_info,
        )

    def _log_level(
        self,
        level: LogLevel,
        message: str,
        module: str,
        extra: Optional[Dict[str, Any]],
        exc_info: Optional[bool],
    ) -> None:
        self.log(level, message, module, extra, exc_info)

    def debug(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
              exc_info: Optional[bool] = None) -> None:
        self._log_level(LogLevel.DEBUG, message, module, extra, exc_info)

    def info(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
             exc_info: Optional[bool] = None) -> None:
        self._log_level(LogLevel.INFO, message, module, extra, exc_info)

    def success(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
                exc_info: Optional[bool] = None) -> None:
        self._log_level(LogLevel.SUCCESS, message, module, extra, exc_info)

    def api(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
            exc_info: Optional[bool] = None) -> None:
        self._log_level(LogLevel.API, message, module, extra, exc_info)

    def warning(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
                exc_info: Optional[bool] = None) -> None:
        self._log_level(LogLevel.WARNING, message, module, extra, exc_info)

    def warn(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
             exc_info: Optional[bool] = None) -> None:
        self.warning(message, module, extra, exc_info)

    def error(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
              exc_info: Optional[bool] = None) -> None:
        self._log_level(LogLevel.ERROR, message, module, extra, exc_info)

    def critical(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
                 exc_info: Optional[bool] = None) -> None:
        self._log_level(LogLevel.CRITICAL, message, module, extra, exc_info)

    def fatal(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None,
              exc_info: Optional[bool] = None) -> None:
        self.critical(message, module, extra, exc_info)

    def flush(self) -> None:
        """等待当前队列排空并刷新所有 handler。"""
        if self._running:
            self._queue.join()
        with self._handlers_lock:
            handlers = tuple(self.handlers)
        for handler in handlers:
            try:
                handler.flush()
            except (OSError, IOError, RuntimeError, ValueError):
                pass

    def close(self) -> None:
        """停止 worker、排空队列并关闭全部 handler，操作幂等。"""
        if self._running:
            self._queue.put(self._STOP)
            self._running = False
            if self._worker_thread is not None:
                self._worker_thread.join(timeout=2.0)
        self.remove_stdlib_bridge()
        if self._ingress_handler in self._stdlib_logger.handlers:
            self._stdlib_logger.removeHandler(self._ingress_handler)
        self.flush()
        with self._handlers_lock:
            handlers = tuple(self.handlers)
            self.handlers.clear()
        for handler in handlers:
            try:
                handler.close()
            except (OSError, IOError, RuntimeError, ValueError):
                pass

    def shutdown(self) -> None:
        """``close`` 的别名，供进程退出钩子统一调用。"""
        self.close()

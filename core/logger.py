"""中心化日志管理系统

提供统一的日志记录功能，支持：
1. 多级别日志（DEBUG, INFO, WARNING, ERROR, CRITICAL, SUCCESS, API）
2. 多处理器（UI终端、文件、控制台）
3. 结构化日志（时间戳、模块、级别、消息）
4. 线程安全
5. 配置化管理
6. 可选的文件持久化
"""

import os
import sys
import time
import threading
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field, asdict
from queue import Queue, Empty

from core.types import LogCallback


class LogLevel(Enum):
    """标准日志级别枚举

    包含标准日志级别以及项目特定的 SUCCESS 和 API 级别。
    """
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    SUCCESS = 25
    API = 15

    @classmethod
    def from_string(cls, level_str: str) -> 'LogLevel':
        """从字符串转换为 LogLevel 枚举

        Args:
            level_str: 日志级别字符串

        Returns:
            对应的 LogLevel 枚举值，默认返回 INFO
        """
        level_str = level_str.upper()
        level_map: Dict[str, LogLevel] = {
            "DEBUG": cls.DEBUG,
            "INFO": cls.INFO,
            "WARNING": cls.WARNING,
            "WARN": cls.WARNING,
            "ERROR": cls.ERROR,
            "CRITICAL": cls.CRITICAL,
            "SUCCESS": cls.SUCCESS,
            "API": cls.API,
        }
        return level_map.get(level_str, cls.INFO)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, LogLevel):
            return self.value < other.value
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, LogLevel):
            return self.value <= other.value
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, LogLevel):
            return self.value > other.value
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, LogLevel):
            return self.value >= other.value
        return NotImplemented


@dataclass
class LogRecord:
    """结构化日志记录

    包含日志的完整信息，包括时间戳、级别、消息、模块等。
    """
    timestamp: datetime
    level: LogLevel
    message: str
    module: str = ""
    thread_id: int = 0
    thread_name: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式

        Returns:
            包含所有日志信息的字典
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.name,
            "message": self.message,
            "module": self.module,
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            **self.extra
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串

        Returns:
            JSON 格式的日志记录
        """
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def format_text(self, include_timestamp: bool = True, include_module: bool = True) -> str:
        """格式化为文本

        Args:
            include_timestamp: 是否包含时间戳
            include_module: 是否包含模块名

        Returns:
            格式化后的文本字符串
        """
        parts: List[str] = []

        if include_timestamp:
            parts.append(f"[{self.timestamp.strftime('%H:%M:%S')}]")

        parts.append(f"[{self.level.name}]")

        if include_module and self.module:
            parts.append(f"[{self.module}]")

        parts.append(self.message)

        return " ".join(parts)


class LogHandler:
    """日志处理器基类

    所有日志处理器都需要继承此类并实现 handle 方法。
    """

    def __init__(self, level: LogLevel = LogLevel.INFO) -> None:
        self.level: LogLevel = level
        self.formatter: Optional[Any] = None

    def set_level(self, level: LogLevel) -> None:
        """设置处理器级别

        Args:
            level: 新的日志级别
        """
        self.level = level

    def can_handle(self, record: LogRecord) -> bool:
        """检查是否可以处理该日志记录

        Args:
            record: 要检查的日志记录

        Returns:
            如果记录级别大于等于处理器级别返回 True
        """
        return record.level >= self.level

    def handle(self, record: LogRecord) -> None:
        """处理日志记录

        Args:
            record: 要处理的日志记录

        Raises:
            NotImplementedError: 子类必须实现此方法
        """
        raise NotImplementedError

    def flush(self) -> None:
        """刷新缓冲区"""
        pass

    def close(self) -> None:
        """关闭处理器"""
        pass


class ConsoleHandler(LogHandler):
    """控制台日志处理器

    将日志输出到标准输出或标准错误，并支持颜色显示。
    """

    def __init__(self, level: LogLevel = LogLevel.INFO) -> None:
        super().__init__(level)
        self._colors: Dict[LogLevel, str] = {
            LogLevel.DEBUG: "\033[36m",
            LogLevel.INFO: "\033[32m",
            LogLevel.SUCCESS: "\033[92m",
            LogLevel.API: "\033[34m",
            LogLevel.WARNING: "\033[33m",
            LogLevel.ERROR: "\033[31m",
            LogLevel.CRITICAL: "\033[91m",
        }
        self._reset: str = "\033[0m"

    def handle(self, record: LogRecord) -> None:
        """输出日志到控制台

        Args:
            record: 要输出的日志记录
        """
        if not self.can_handle(record):
            return

        color = self._colors.get(record.level, "")
        level_name = record.level.name

        timestamp = record.timestamp.strftime("%H:%M:%S")
        module_str = f" [{record.module}]" if record.module else ""

        message = record.format_text(include_timestamp=False, include_module=False)

        output = f"{color}[{timestamp}] [{level_name}]{module_str} {message}{self._reset}"

        if record.level >= LogLevel.ERROR:
            print(output, file=sys.stderr)
        else:
            print(output, file=sys.stdout)


class FileHandler(LogHandler):
    """文件日志处理器

    将日志写入文件，支持日志轮转。当日志文件大小达到上限时，
    会自动备份并重命名旧文件。
    """

    def __init__(
        self,
        filepath: Union[str, Path],
        level: LogLevel = LogLevel.INFO,
        max_size: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        mode: str = "a",
        encoding: str = "utf-8",
        use_json: bool = False
    ) -> None:
        super().__init__(level)
        self.filepath: Path = Path(filepath)
        self.max_size: int = max_size
        self.backup_count: int = backup_count
        self.mode: str = mode
        self.encoding: str = encoding
        self.use_json: bool = use_json

        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        self._file: Optional[Any] = None
        self._open_file()

    def _open_file(self) -> None:
        """打开日志文件"""
        if self._file is not None and not self._file.closed:
            self._file.close()

        self._file = open(self.filepath, self.mode, encoding=self.encoding)

    def _should_rotate(self) -> bool:
        """检查是否需要轮转

        Returns:
            如果文件大小达到上限返回 True
        """
        try:
            return self.filepath.stat().st_size >= self.max_size
        except (OSError, IOError):
            return False

    def _rotate(self) -> None:
        """执行日志轮转"""
        if self.backup_count <= 0:
            return

        if self._file and not self._file.closed:
            self._file.close()

        for i in range(self.backup_count - 1, 0, -1):
            old_file = self.filepath.with_suffix(f".{i}.log")
            new_file = self.filepath.with_suffix(f".{i+1}.log")
            if old_file.exists():
                old_file.rename(new_file)

        backup_file = self.filepath.with_suffix(".1.log")
        if self.filepath.exists():
            self.filepath.rename(backup_file)

        self._open_file()

    def handle(self, record: LogRecord) -> None:
        """写入日志到文件

        Args:
            record: 要写入的日志记录
        """
        if not self.can_handle(record):
            return

        if self._should_rotate():
            self._rotate()

        if self.use_json:
            log_line = record.to_json() + "\n"
        else:
            log_line = record.format_text() + "\n"

        try:
            if self._file:
                self._file.write(log_line)
                self._file.flush()
        except (OSError, IOError):
            try:
                self._open_file()
                if self._file:
                    self._file.write(log_line)
                    self._file.flush()
            except Exception:
                pass

    def flush(self) -> None:
        """刷新文件缓冲区"""
        if self._file and not self._file.closed:
            self._file.flush()

    def close(self) -> None:
        """关闭文件"""
        if self._file and not self._file.closed:
            self._file.close()
            self._file = None


class UIHandler(LogHandler):
    """UI 日志处理器

    通过回调函数将日志发送到 UI 界面显示。
    """

    def __init__(self, log_callback: LogCallback, level: LogLevel = LogLevel.INFO) -> None:
        super().__init__(level)
        self.log_callback: LogCallback = log_callback

        self._tag_map: Dict[LogLevel, str] = {
            LogLevel.INFO: "info",
            LogLevel.SUCCESS: "success",
            LogLevel.WARNING: "warn",
            LogLevel.ERROR: "error",
            LogLevel.API: "api",
            LogLevel.DEBUG: "info",
            LogLevel.CRITICAL: "error",
        }

    def handle(self, record: LogRecord) -> None:
        """通过回调发送日志到 UI

        Args:
            record: 要发送的日志记录
        """
        if not self.can_handle(record):
            return

        tag = self._tag_map.get(record.level, "info")

        parts: List[str] = []
        if record.module:
            parts.append(f"[{record.module}]")
        parts.append(record.message)
        message = " ".join(parts)

        try:
            self.log_callback(message, tag)
        except Exception:
            pass


class LogManager:
    """中心化日志管理器（单例模式）

    管理所有日志处理器，提供统一的日志记录接口。
    使用异步队列处理日志，确保线程安全。
    """

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
        """启动日志工作线程"""
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            name="LogManager-Worker",
            daemon=True
        )
        self._worker_thread.start()

    def _process_queue(self) -> None:
        """处理日志队列"""
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
        """分发日志记录到所有处理器

        Args:
            record: 要分发的日志记录
        """
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
        """添加日志处理器

        Args:
            handler: 要添加的日志处理器
        """
        self.handlers.append(handler)

    def remove_handler(self, handler: LogHandler) -> None:
        """移除日志处理器

        Args:
            handler: 要移除的日志处理器
        """
        if handler in self.handlers:
            self.handlers.remove(handler)
            handler.close()

    def set_level(self, level: LogLevel) -> None:
        """设置全局日志级别

        Args:
            level: 新的全局日志级别
        """
        self.min_level = level

    def set_module_level(self, module: str, level: LogLevel) -> None:
        """设置特定模块的日志级别

        Args:
            module: 模块名称
            level: 该模块的日志级别
        """
        self._module_levels[module] = level

    def log(
        self,
        level: LogLevel,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """记录日志（线程安全）

        Args:
            level: 日志级别
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        current_thread = threading.current_thread()

        record = LogRecord(
            timestamp=datetime.now(),
            level=level,
            message=message,
            module=module,
            thread_id=current_thread.ident or 0,
            thread_name=current_thread.name,
            extra=extra or {}
        )

        self._queue.put(record)

    def debug(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        """记录 DEBUG 级别日志

        Args:
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        self.log(LogLevel.DEBUG, message, module, extra)

    def info(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        """记录 INFO 级别日志

        Args:
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        self.log(LogLevel.INFO, message, module, extra)

    def success(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        """记录 SUCCESS 级别日志

        Args:
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        self.log(LogLevel.SUCCESS, message, module, extra)

    def api(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        """记录 API 级别日志

        Args:
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        self.log(LogLevel.API, message, module, extra)

    def warning(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        """记录 WARNING 级别日志

        Args:
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        self.log(LogLevel.WARNING, message, module, extra)

    def error(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        """记录 ERROR 级别日志

        Args:
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        self.log(LogLevel.ERROR, message, module, extra)

    def critical(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        """记录 CRITICAL 级别日志

        Args:
            message: 日志消息
            module: 模块名称
            extra: 额外信息
        """
        self.log(LogLevel.CRITICAL, message, module, extra)

    def flush(self) -> None:
        """刷新所有处理器"""
        for handler in self.handlers:
            try:
                handler.flush()
            except Exception:
                pass

    def shutdown(self) -> None:
        """关闭日志管理器"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)

        for handler in self.handlers:
            try:
                handler.close()
            except Exception:
                pass

        self.handlers.clear()


logger: LogManager = LogManager()


def setup_default_logging(
    enable_console: bool = True,
    enable_file: bool = True,
    file_path: Optional[Path] = None,
    enable_ui: bool = False,
    ui_callback: Optional[LogCallback] = None,
    level: LogLevel = LogLevel.INFO
) -> None:
    """设置默认日志配置

    Args:
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件日志
        file_path: 文件日志路径
        enable_ui: 是否启用 UI 输出
        ui_callback: UI 回调函数
        level: 全局日志级别
    """
    for handler in logger.handlers[:]:
        logger.remove_handler(handler)

    logger.set_level(level)

    if enable_console:
        console_handler = ConsoleHandler(level=level)
        logger.add_handler(console_handler)

    if enable_file:
        if file_path is None:
            log_dir = Path.home() / ".mcsavehelper" / "logs"
            file_path = log_dir / "app.log"

        file_handler = FileHandler(
            filepath=file_path,
            level=level,
            max_size=10 * 1024 * 1024,
            backup_count=5
        )
        logger.add_handler(file_handler)

    if enable_ui and ui_callback:
        ui_handler = UIHandler(ui_callback, level=level)
        logger.add_handler(ui_handler)

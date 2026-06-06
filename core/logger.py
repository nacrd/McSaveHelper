"""
中心化日志管理系统

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
    """标准日志级别枚举"""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    
    # 项目特定级别（保持向后兼容）
    SUCCESS = 25  # 介于INFO和WARNING之间
    API = 15      # 介于DEBUG和INFO之间
    
    @classmethod
    def from_string(cls, level_str: str) -> 'LogLevel':
        """从字符串转换为LogLevel枚举"""
        level_str = level_str.upper()
        level_map = {
            "DEBUG": cls.DEBUG,
            "INFO": cls.INFO,
            "WARNING": cls.WARNING,
            "WARN": cls.WARNING,  # 兼容WARN
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
    """结构化日志记录"""
    timestamp: datetime
    level: LogLevel
    message: str
    module: str = ""
    thread_id: int = 0
    thread_name: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
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
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    def format_text(self, include_timestamp: bool = True, include_module: bool = True) -> str:
        """格式化为文本"""
        parts = []
        
        if include_timestamp:
            parts.append(f"[{self.timestamp.strftime('%H:%M:%S')}]")
        
        parts.append(f"[{self.level.name}]")
        
        if include_module and self.module:
            parts.append(f"[{self.module}]")
        
        parts.append(self.message)
        
        return " ".join(parts)


class LogHandler:
    """日志处理器基类"""
    
    def __init__(self, level: LogLevel = LogLevel.INFO) -> None:
        self.level = level
        self.formatter = None
    
    def set_level(self, level: LogLevel) -> None:
        """设置处理器级别"""
        self.level = level
    
    def can_handle(self, record: LogRecord) -> bool:
        """检查是否可以处理该日志记录"""
        return record.level >= self.level
    
    def handle(self, record: LogRecord) -> None:
        """处理日志记录（子类必须实现）"""
        raise NotImplementedError
    
    def flush(self) -> None:
        """刷新缓冲区（可选实现）"""
        pass
    
    def close(self) -> None:
        """关闭处理器（可选实现）"""
        pass


class ConsoleHandler(LogHandler):
    """控制台处理器"""
    
    def __init__(self, level: LogLevel = LogLevel.INFO) -> None:
        super().__init__(level)
        self._colors = {
            LogLevel.DEBUG: "\033[36m",    # 青色
            LogLevel.INFO: "\033[32m",     # 绿色
            LogLevel.SUCCESS: "\033[92m",  # 亮绿色
            LogLevel.API: "\033[34m",      # 蓝色
            LogLevel.WARNING: "\033[33m",  # 黄色
            LogLevel.ERROR: "\033[31m",    # 红色
            LogLevel.CRITICAL: "\033[91m", # 亮红色
        }
        self._reset = "\033[0m"
    
    def handle(self, record: LogRecord) -> None:
        """输出到控制台"""
        if not self.can_handle(record):
            return
        
        color = self._colors.get(record.level, "")
        level_name = record.level.name
        
        # 格式化输出
        timestamp = record.timestamp.strftime("%H:%M:%S")
        module_str = f" [{record.module}]" if record.module else ""
        
        message = record.format_text(include_timestamp=False, include_module=False)
        
        # 构建输出行
        output = f"{color}[{timestamp}] [{level_name}]{module_str} {message}{self._reset}"
        
        # 根据级别选择输出流
        if record.level >= LogLevel.ERROR:
            print(output, file=sys.stderr)
        else:
            print(output, file=sys.stdout)


class FileHandler(LogHandler):
    """文件处理器（支持日志轮转）"""
    
    def __init__(
        self,
        filepath: Union[str, Path],
        level: LogLevel = LogLevel.INFO,
        max_size: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        mode: str = "a",
        encoding: str = "utf-8",
        use_json: bool = False
    ) -> None:
        super().__init__(level)
        self.filepath = Path(filepath)
        self.max_size = max_size
        self.backup_count = backup_count
        self.mode = mode
        self.encoding = encoding
        self.use_json = use_json
        
        # 确保目录存在
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        
        self._file = None
        self._open_file()
    
    def _open_file(self) -> None:
        """打开日志文件"""
        if self._file is not None and not self._file.closed:
            self._file.close()
        
        self._file = open(self.filepath, self.mode, encoding=self.encoding)
    
    def _should_rotate(self) -> bool:
        """检查是否需要轮转"""
        try:
            return self.filepath.stat().st_size >= self.max_size
        except (OSError, IOError):
            return False
    
    def _rotate(self) -> None:
        """执行日志轮转"""
        if self.backup_count <= 0:
            return
        
        # 关闭当前文件
        if self._file and not self._file.closed:
            self._file.close()
        
        # 轮转现有备份文件
        for i in range(self.backup_count - 1, 0, -1):
            old_file = self.filepath.with_suffix(f".{i}.log")
            new_file = self.filepath.with_suffix(f".{i+1}.log")
            if old_file.exists():
                old_file.rename(new_file)
        
        # 移动当前日志为备份1
        backup_file = self.filepath.with_suffix(".1.log")
        if self.filepath.exists():
            self.filepath.rename(backup_file)
        
        # 重新打开文件
        self._open_file()
    
    def handle(self, record: LogRecord) -> None:
        """写入到文件"""
        if not self.can_handle(record):
            return
        
        # 检查是否需要轮转
        if self._should_rotate():
            self._rotate()
        
        # 格式化日志
        if self.use_json:
            log_line = record.to_json() + "\n"
        else:
            log_line = record.format_text() + "\n"
        
        # 写入文件
        try:
            if self._file:
                self._file.write(log_line)
                self._file.flush()
        except (OSError, IOError) as e:
            # 文件写入失败，尝试重新打开
            print(f"日志文件写入失败: {e}", file=sys.stderr)
            try:
                self._open_file()
                if self._file:
                    self._file.write(log_line)
                    self._file.flush()
            except Exception:
                pass  # 放弃写入
    
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
    """UI处理器（适配现有UI系统）"""
    
    def __init__(self, log_callback: LogCallback, level: LogLevel = LogLevel.INFO) -> None:
        super().__init__(level)
        self.log_callback = log_callback
        
        # 级别到标签的映射（保持与现有UI兼容）
        self._tag_map = {
            LogLevel.INFO: "info",
            LogLevel.SUCCESS: "success",
            LogLevel.WARNING: "warn",
            LogLevel.ERROR: "error",
            LogLevel.API: "api",
            LogLevel.DEBUG: "info",  # DEBUG使用info标签
            LogLevel.CRITICAL: "error",  # CRITICAL使用error标签
        }
    
    def handle(self, record: LogRecord) -> None:
        """通过回调发送到UI"""
        if not self.can_handle(record):
            return
        
        # 获取对应的UI标签
        tag = self._tag_map.get(record.level, "info")
        
        # 格式化消息（不包含时间戳和级别名称，因为UI回调会添加）
        parts = []
        if record.module:
            parts.append(f"[{record.module}]")
        parts.append(record.message)
        message = " ".join(parts)
        
        # 调用UI回调
        try:
            self.log_callback(message, tag)
        except Exception:
            # UI回调失败，静默处理
            pass


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
        self.min_level = LogLevel.INFO
        self._queue = Queue()
        self._worker_thread = None
        self._running = False
        self._module_levels: Dict[str, LogLevel] = {}
        
        # 启动工作线程
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
                # 使用超时避免永久阻塞
                record = self._queue.get(timeout=0.1)
                self._dispatch(record)
                self._queue.task_done()
            except Empty:
                continue
            except Exception as e:
                # 防止工作线程崩溃
                print(f"日志处理器异常: {e}", file=sys.stderr)
    
    def _dispatch(self, record: LogRecord) -> None:
        """分发日志记录到所有处理器"""
        # 检查模块级别过滤
        module_level = self._module_levels.get(record.module)
        if module_level and record.level < module_level:
            return
        
        # 检查全局级别过滤
        if record.level < self.min_level:
            return
        
        # 发送到所有处理器
        for handler in self.handlers:
            try:
                handler.handle(record)
            except Exception as e:
                # 处理器失败，但不影响其他处理器
                print(f"日志处理器 {handler.__class__.__name__} 失败: {e}", file=sys.stderr)
    
    def add_handler(self, handler: LogHandler) -> None:
        """添加日志处理器"""
        self.handlers.append(handler)
    
    def remove_handler(self, handler: LogHandler) -> None:
        """移除日志处理器"""
        if handler in self.handlers:
            self.handlers.remove(handler)
            handler.close()
    
    def set_level(self, level: LogLevel) -> None:
        """设置全局日志级别"""
        self.min_level = level
    
    def set_module_level(self, module: str, level: LogLevel) -> None:
        """设置特定模块的日志级别"""
        self._module_levels[module] = level
    
    def log(
        self,
        level: LogLevel,
        message: str,
        module: str = "",
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """记录日志（线程安全）"""
        # 获取当前线程信息
        current_thread = threading.current_thread()
        
        # 创建日志记录
        record = LogRecord(
            timestamp=datetime.now(),
            level=level,
            message=message,
            module=module,
            thread_id=current_thread.ident or 0,
            thread_name=current_thread.name,
            extra=extra or {}
        )
        
        # 添加到队列（异步处理）
        self._queue.put(record)
    
    # 便捷方法
    def debug(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.DEBUG, message, module, extra)
    
    def info(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.INFO, message, module, extra)
    
    def success(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.SUCCESS, message, module, extra)
    
    def api(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.API, message, module, extra)
    
    def warning(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.WARNING, message, module, extra)
    
    def error(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
        self.log(LogLevel.ERROR, message, module, extra)
    
    def critical(self, message: str, module: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
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
        
        # 关闭所有处理器
        for handler in self.handlers:
            try:
                handler.close()
            except Exception:
                pass
        
        self.handlers.clear()


# 全局日志管理器实例
logger = LogManager()


def setup_default_logging(
    enable_console: bool = True,
    enable_file: bool = True,
    file_path: Optional[Path] = None,
    enable_ui: bool = False,
    ui_callback: Optional[LogCallback] = None,
    level: LogLevel = LogLevel.INFO
) -> None:
    """
    设置默认日志配置
    
    Args:
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件日志
        file_path: 文件日志路径（默认：~/.mcsavehelper/logs/app.log）
        enable_ui: 是否启用UI输出
        ui_callback: UI回调函数
        level: 全局日志级别
    """
    # 清除现有处理器
    for handler in logger.handlers[:]:
        logger.remove_handler(handler)
    
    # 设置全局级别
    logger.set_level(level)
    
    # 控制台处理器
    if enable_console:
        console_handler = ConsoleHandler(level=level)
        logger.add_handler(console_handler)
    
    # 文件处理器
    if enable_file:
        if file_path is None:
            log_dir = Path.home() / ".mcsavehelper" / "logs"
            file_path = log_dir / "app.log"
        
        file_handler = FileHandler(
            filepath=file_path,
            level=level,
            max_size=10 * 1024 * 1024,  # 10MB
            backup_count=5
        )
        logger.add_handler(file_handler)
    
    # UI处理器
    if enable_ui and ui_callback:
        ui_handler = UIHandler(ui_callback, level=level)
        logger.add_handler(ui_handler)

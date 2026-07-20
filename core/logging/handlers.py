"""Log handlers: base, console, file, UI."""
import os
import sys
from pathlib import Path
from typing import Any, Optional, Union

from core.types import LogCallback
from .models import LogLevel, LogRecord


class LogHandler:
    """日志处理器基类"""

    def __init__(self, level: LogLevel = LogLevel.INFO) -> None:
        self.level: LogLevel = level
        self.formatter: Optional[Any] = None

    def set_level(self, level: LogLevel) -> None:
        self.level = level

    def can_handle(self, record: LogRecord) -> bool:
        return record.level >= self.level

    def handle(self, record: LogRecord) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class ConsoleHandler(LogHandler):
    """控制台日志处理器（支持颜色）"""

    _COLORS = {
        LogLevel.DEBUG: "\033[36m", LogLevel.INFO: "\033[32m",
        LogLevel.SUCCESS: "\033[92m", LogLevel.API: "\033[34m",
        LogLevel.WARNING: "\033[33m", LogLevel.ERROR: "\033[31m",
        LogLevel.CRITICAL: "\033[91m",
    }
    _RESET = "\033[0m"

    def handle(self, record: LogRecord) -> None:
        if not self.can_handle(record):
            return
        color = self._COLORS.get(record.level, "")
        ts = record.timestamp.strftime("%H:%M:%S")
        module_str = f" [{record.module}]" if record.module else ""
        msg = record.format_text(include_timestamp=False, include_module=False, include_level=False)
        output = f"{color}[{ts}] [{record.level.name}]{module_str} {msg}{self._RESET}"
        if record.level >= LogLevel.ERROR:
            print(output, file=sys.stderr)
        else:
            print(output, file=sys.stdout)


class FileHandler(LogHandler):
    """文件日志处理器（支持轮转）"""

    def __init__(self, filepath: Union[str, Path], level: LogLevel = LogLevel.INFO,
                 max_size: int = 10 * 1024 * 1024, backup_count: int = 5,
                 mode: str = "a", encoding: str = "utf-8", use_json: bool = False) -> None:
        super().__init__(level)
        self.filepath = Path(filepath)
        self.max_size = max_size
        self.backup_count = backup_count
        self.mode = mode
        self.encoding = encoding
        self.use_json = use_json
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._file: Optional[Any] = None
        self._open_file()

    def _open_file(self) -> None:
        if self._file is not None and not self._file.closed:
            self._file.close()
        self._file = open(self.filepath, self.mode, encoding=self.encoding)

    def _should_rotate(self) -> bool:
        try:
            return self.filepath.stat().st_size >= self.max_size
        except (OSError, IOError):
            return False

    def _rotate(self) -> None:
        if self.backup_count <= 0:
            return
        try:
            if self._file and not self._file.closed:
                self._file.close()
            oldest = self.filepath.with_suffix(f".{self.backup_count}.log")
            oldest.unlink(missing_ok=True)
            for i in range(self.backup_count - 1, 0, -1):
                old_file = self.filepath.with_suffix(f".{i}.log")
                new_file = self.filepath.with_suffix(f".{i + 1}.log")
                if old_file.exists():
                    os.replace(old_file, new_file)
            backup_file = self.filepath.with_suffix(".1.log")
            if self.filepath.exists():
                os.replace(self.filepath, backup_file)
        finally:
            self._open_file()

    def handle(self, record: LogRecord) -> None:
        if not self.can_handle(record):
            return
        if self._should_rotate():
            self._rotate()
        log_line = (record.to_json() if self.use_json else record.format_text()) + "\n"
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
            except (OSError, IOError):
                # Logging must not raise into application code.
                pass

    def flush(self) -> None:
        if self._file and not self._file.closed:
            self._file.flush()

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()
            self._file = None


class UIHandler(LogHandler):
    """UI 日志处理器（通过回调发送到界面）"""

    _TAG_MAP = {
        LogLevel.INFO: "info", LogLevel.SUCCESS: "success",
        LogLevel.WARNING: "warn", LogLevel.ERROR: "error",
        LogLevel.API: "api", LogLevel.DEBUG: "info", LogLevel.CRITICAL: "error",
    }

    def __init__(self, log_callback: LogCallback, level: LogLevel = LogLevel.INFO) -> None:
        super().__init__(level)
        self.log_callback = log_callback

    def handle(self, record: LogRecord) -> None:
        if not self.can_handle(record):
            return
        tag = self._TAG_MAP.get(record.level, "info")
        parts = [f"[{record.module}]"] if record.module else []
        parts.append(record.message)
        try:
            self.log_callback(" ".join(parts), tag)
        except Exception:
            # UI log sinks may be disposed during teardown.
            pass

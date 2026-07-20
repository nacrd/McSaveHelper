"""日志级别枚举与结构化日志记录模型。"""
import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List
from dataclasses import dataclass, field


class LogLevel(Enum):
    """标准日志级别枚举（含 SUCCESS / API 扩展级别）。"""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    SUCCESS = 25
    API = 15

    @classmethod
    def from_string(cls, level_str: str) -> 'LogLevel':
        """将大小写不敏感的级别名解析为枚举。

        Args:
            level_str: 如 ``info`` / ``WARN``；未知名回退 INFO。

        Returns:
            对应 ``LogLevel`` 成员。
        """
        level_str = level_str.upper()
        level_map = {
            "DEBUG": cls.DEBUG, "INFO": cls.INFO, "WARNING": cls.WARNING,
            "WARN": cls.WARNING, "ERROR": cls.ERROR, "CRITICAL": cls.CRITICAL,
            "SUCCESS": cls.SUCCESS, "API": cls.API,
        }
        return level_map.get(level_str, cls.INFO)

    def __lt__(self, other: Any) -> bool:
        return (
            self.value < other.value
            if isinstance(other, LogLevel)
            else NotImplemented
        )

    def __le__(self, other: Any) -> bool:
        return (
            self.value <= other.value
            if isinstance(other, LogLevel)
            else NotImplemented
        )

    def __gt__(self, other: Any) -> bool:
        return (
            self.value > other.value
            if isinstance(other, LogLevel)
            else NotImplemented
        )

    def __ge__(self, other: Any) -> bool:
        return (
            self.value >= other.value
            if isinstance(other, LogLevel)
            else NotImplemented
        )


@dataclass
class LogRecord:
    """结构化日志记录。

    Attributes:
        timestamp: 记录时间。
        level: 日志级别。
        message: 主消息。
        module: 可选模块标签。
        thread_id: 线程 ID。
        thread_name: 线程名。
        extra: 附加键值。
    """
    timestamp: datetime
    level: LogLevel
    message: str
    module: str = ""
    thread_id: int = 0
    thread_name: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（含 extra 字段展开）。

        Returns:
            可 JSON 化的字段字典。
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
        """JSON 字符串形式（ensure_ascii=False）。

        Returns:
            UTF-8 友好的 JSON 文本。
        """
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def format_text(
        self,
        include_timestamp: bool = True,
        include_module: bool = True,
        include_level: bool = True,
    ) -> str:
        """人类可读单行日志文本。

        Args:
            include_timestamp: 是否含时间。
            include_module: 是否含 module 字段。
            include_level: 是否含级别名。

        Returns:
            空格拼接的单行字符串。
        """
        parts: List[str] = []
        if include_timestamp:
            parts.append(f"[{self.timestamp.strftime('%H:%M:%S')}]")
        if include_level:
            parts.append(f"[{self.level.name}]")
        if include_module and self.module:
            parts.append(f"[{self.module}]")
        parts.append(self.message)
        return " ".join(parts)

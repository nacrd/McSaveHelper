"""Log level enum and log record dataclass."""
import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List
from dataclasses import dataclass, field


class LogLevel(Enum):
    """标准日志级别枚举"""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    SUCCESS = 25
    API = 15

    @classmethod
    def from_string(cls, level_str: str) -> 'LogLevel':
        level_str = level_str.upper()
        level_map = {
            "DEBUG": cls.DEBUG, "INFO": cls.INFO, "WARNING": cls.WARNING,
            "WARN": cls.WARNING, "ERROR": cls.ERROR, "CRITICAL": cls.CRITICAL,
            "SUCCESS": cls.SUCCESS, "API": cls.API,
        }
        return level_map.get(level_str, cls.INFO)

    def __lt__(self, other: Any) -> bool:
        return self.value < other.value if isinstance(other, LogLevel) else NotImplemented

    def __le__(self, other: Any) -> bool:
        return self.value <= other.value if isinstance(other, LogLevel) else NotImplemented

    def __gt__(self, other: Any) -> bool:
        return self.value > other.value if isinstance(other, LogLevel) else NotImplemented

    def __ge__(self, other: Any) -> bool:
        return self.value >= other.value if isinstance(other, LogLevel) else NotImplemented


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
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def format_text(self, include_timestamp: bool = True,
                    include_module: bool = True, include_level: bool = True) -> str:
        parts: List[str] = []
        if include_timestamp:
            parts.append(f"[{self.timestamp.strftime('%H:%M:%S')}]")
        if include_level:
            parts.append(f"[{self.level.name}]")
        if include_module and self.module:
            parts.append(f"[{self.module}]")
        parts.append(self.message)
        return " ".join(parts)

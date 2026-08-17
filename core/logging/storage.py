"""JSONL log storage, rotation, streaming queries, and aggregation."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence

from .handlers import LogHandler
from .models import LogLevel, LogRecord

_DATE_PATTERN = re.compile(r"^app-(\d{4}-\d{2}-\d{2})(?:\.(\d+))?\.jsonl$")
_PATH_PATTERN = re.compile(r"^(?P<name>[^:]+):(?P<offset>\d+)$")
_REDACTED_KEYS = {"password", "token", "secret", "authorization", "cookie"}
_HEX_PATTERN = re.compile(r"0x[0-9a-fA-F]+")
_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
_PATH_NUMBER_PATTERN = re.compile(r"([\\/])\d+(?=[\\/])")


def _utc_microseconds(value: datetime) -> int:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return int(aware.astimezone(timezone.utc).timestamp() * 1_000_000)


def _safe_json_value(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "<nested value truncated>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _REDACTED_KEYS:
                result[key_text] = "<redacted>"
            else:
                result[key_text] = _safe_json_value(item, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_safe_json_value(item, depth + 1) for item in value]
    return str(value)


def compute_fingerprint(record: LogRecord) -> Optional[str]:
    """计算异常或错误消息的稳定 SHA-256 指纹。"""
    if record.level < LogLevel.ERROR:
        return None
    parts = [record.module, record.exception_type or "", record.message]
    if record.stack_trace:
        frames = [
            line.strip()
            for line in record.stack_trace.splitlines()
            if line.strip().startswith("File ")
        ]
        parts.extend(frames[:3])
    normalized = "\n".join(parts)
    normalized = _HEX_PATTERN.sub("0x#", normalized)
    normalized = _PATH_NUMBER_PATTERN.sub(r"\1#", normalized)
    normalized = _NUMBER_PATTERN.sub("#", normalized)
    digest = hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()
    return f"sha256:{digest}"


def record_to_payload(record: LogRecord) -> Dict[str, Any]:
    """将内部记录转换为 JSONL schema v1。"""
    timestamp = record.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.astimezone()
    category = _category_for_level(record.level)
    fingerprint = record.fingerprint or compute_fingerprint(record)
    return {
        "schema_version": 1,
        "timestamp": timestamp.isoformat(),
        "timestamp_utc_us": _utc_microseconds(timestamp),
        "level": record.level.name,
        "category": category,
        "module": record.module,
        "logger_name": record.logger_name,
        "process_id": record.process_id,
        "thread_id": record.thread_id,
        "thread_name": record.thread_name,
        "message": record.message,
        "exception_type": record.exception_type,
        "exception_message": record.exception_message,
        "stack_trace": record.stack_trace,
        "extra": _safe_json_value(record.extra),
        "fingerprint": fingerprint,
        "created_at_utc_us": _utc_microseconds(record.created_at or timestamp),
    }


def _category_for_level(level: LogLevel) -> str:
    if level <= LogLevel.DEBUG:
        return "DEBUG"
    if level < LogLevel.WARNING:
        return "INFO"
    if level < LogLevel.ERROR:
        return "WARN"
    if level < LogLevel.CRITICAL:
        return "ERROR"
    return "FATAL"


@dataclass(frozen=True)
class StoredLog:
    """已从 JSONL 解析的日志摘要及其文件定位。"""

    record_id: str
    source_file: str
    source_offset: int
    timestamp: datetime
    timestamp_utc_us: int
    level: str
    category: str
    module: str
    logger_name: str
    process_id: int
    thread_id: int
    thread_name: str
    message: str
    exception_type: Optional[str]
    exception_message: Optional[str]
    stack_trace: Optional[str]
    extra: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: Optional[str] = None


@dataclass(frozen=True)
class LogQuery:
    """JSONL 流式查询条件。"""

    levels: frozenset[str] = frozenset()
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    keyword: str = ""
    module: str = ""
    limit: int = 200
    descending: bool = True


@dataclass(frozen=True)
class LogPage:
    """一页查询结果。"""

    entries: tuple[StoredLog, ...]
    scanned_files: int
    malformed_lines: int
    next_cursor: Optional[str]


@dataclass(frozen=True)
class LogTrendPoint:
    """单日级别统计。"""

    day: date
    total: int
    by_category: Mapping[str, int]


@dataclass(frozen=True)
class LogStatistics:
    """日志统计结果。"""

    total: int
    by_category: Mapping[str, int]
    trend: tuple[LogTrendPoint, ...]
    malformed_lines: int = 0


class DailyJsonlHandler(LogHandler):
    """按天、按大小滚动的 JSONL handler。

    该 handler 只负责本地顺序写入；调用线程由 ``LogManager`` 的 worker 保证，
    但自身仍使用锁以支持直接测试和显式 flush。
    """

    def __init__(
        self,
        log_root: str | Path,
        level: LogLevel = LogLevel.DEBUG,
        max_file_size: int = 25 * 1024 * 1024,
        retention_days: int = 90,
        max_total_bytes: int = 500 * 1024 * 1024,
        clock: Optional[Callable[[], datetime]] = None,
        max_record_size: int = 1024 * 1024,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(level)
        self.log_root = Path(log_root)
        self.archive_dir = self.log_root / "archive"
        self.emergency_dir = self.log_root / "emergency"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.emergency_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = max(1, max_file_size)
        self.retention_days = max(1, retention_days)
        self.max_total_bytes = max(1, max_total_bytes)
        self.max_record_size = max(1024, max_record_size)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._status_callback = status_callback
        self._lock = threading.RLock()
        self._file: Optional[Any] = None
        self._path: Optional[Path] = None
        self._day: Optional[date] = None
        self._estimated_total_bytes = _total_size(_list_log_files(self.archive_dir))

    def _filename(self, day: date, index: int) -> str:
        suffix = f".{index}" if index else ""
        return f"app-{day.isoformat()}{suffix}.jsonl"

    def _open_for(self, day: date) -> None:
        if self._file is not None:
            self._file.close()
        candidates = sorted(self.archive_dir.glob(f"app-{day.isoformat()}*.jsonl"))
        path = max(candidates, key=lambda item: _file_index(item.name)) if candidates else (
            self.archive_dir / self._filename(day, 0)
        )
        if path.exists() and path.stat().st_size >= self.max_file_size:
            index = self._next_index(day, candidates)
            path = self.archive_dir / self._filename(day, index)
        self._path = path
        self._day = day
        self._file = open(path, "a", encoding="utf-8", newline="\n")

    def _next_index(self, day: date, candidates: Sequence[Path]) -> int:
        indexes = []
        for candidate in candidates:
            match = _DATE_PATTERN.match(candidate.name)
            if match and match.group(1) == day.isoformat():
                indexes.append(int(match.group(2) or 0))
        return max(indexes, default=0) + 1

    def _rotate_if_needed(self, day: date, line_size: int) -> bool:
        rotated = self._file is None or self._day != day
        if self._file is None or self._day != day:
            self._open_for(day)
        if (
            self._path is not None
            and self._path.stat().st_size + line_size > self.max_file_size
        ):
            candidates = sorted(self.archive_dir.glob(f"app-{day.isoformat()}*.jsonl"))
            index = self._next_index(day, candidates)
            self._open_path(self.archive_dir / self._filename(day, index))
            rotated = True
        return rotated

    def _open_path(self, path: Path) -> None:
        if self._file is not None:
            self._file.close()
        self._path = path
        self._file = open(path, "a", encoding="utf-8", newline="\n")

    def _encode(self, record: LogRecord) -> str:
        payload = record_to_payload(record)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= self.max_record_size:
            return encoded + "\n"
        payload["message"] = _truncate(str(payload["message"]), 64 * 1024)
        payload["stack_trace"] = _truncate(str(payload["stack_trace"] or ""), 256 * 1024)
        payload["extra"] = {"_truncated": True, "original_bytes": len(encoded.encode("utf-8"))}
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

    def _write_emergency(self, line: str) -> None:
        path = self.emergency_dir / f"emergency-{self._clock().date().isoformat()}.log"
        try:
            with open(path, "a", encoding="utf-8", newline="\n") as emergency:
                emergency.write(line)
        except OSError:
            pass

    def set_status_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """设置存储状态回调；回调不得执行磁盘 I/O。"""
        self._status_callback = callback

    def _notify_status(self, message: str) -> None:
        if self._status_callback is None:
            return
        try:
            self._status_callback(message)
        except (RuntimeError, ValueError):
            pass

    def handle(self, record: LogRecord) -> None:
        if not self.can_handle(record):
            return
        line = self._encode(record)
        day = record.timestamp.astimezone().date()
        with self._lock:
            try:
                line_size = len(line.encode("utf-8"))
                rotated = self._rotate_if_needed(day, line_size)
                assert self._file is not None
                self._file.write(line)
                self._file.flush()
                self._estimated_total_bytes += line_size
                if rotated or self._estimated_total_bytes > self.max_total_bytes:
                    self.enforce_retention()
            except (OSError, AssertionError):
                self._write_emergency(line)
                self._notify_status("write_failed")

    def flush(self) -> None:
        with self._lock:
            if self._file is not None and not self._file.closed:
                self._file.flush()

    def enforce_retention(self, now: Optional[datetime] = None) -> int:
        """删除超出日期和总容量上限的归档文件，返回删除数量。"""
        current = (now or self._clock()).date()
        deleted = 0
        with self._lock:
            files = _list_log_files(self.archive_dir)
            for path in files:
                day = _date_from_filename(path.name)
                if day is None or (current - day).days < self.retention_days:
                    continue
                if self._path == path:
                    continue
                if _safe_unlink(path, self.archive_dir):
                    deleted += 1
            files = _list_log_files(self.archive_dir)
            total = _total_size(files)
            for path in files:
                if total <= self.max_total_bytes:
                    break
                if self._path == path:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if _safe_unlink(path, self.archive_dir):
                    total -= size
                    deleted += 1
            if total > self.max_total_bytes:
                self._notify_status("storage_full")
            self._estimated_total_bytes = total
        return deleted

    def clear_archives(self) -> int:
        """关闭活动句柄并删除全部受管 JSONL 归档。"""
        with self._lock:
            if self._file is not None and not self._file.closed:
                self._file.flush()
                self._file.close()
            self._file = None
            self._path = None
            self._day = None
            deleted = sum(
                1 for path in _list_log_files(self.archive_dir)
                if _safe_unlink(path, self.archive_dir)
            )
            self._estimated_total_bytes = 0
            return deleted

    def close(self) -> None:
        with self._lock:
            if self._file is not None and not self._file.closed:
                self._file.flush()
                self._file.close()
            self._file = None
            self._path = None
            self._day = None


class JsonlLogStore:
    """从 JSONL 归档中执行后台可调用的查询、统计和详情读取。"""

    def __init__(self, log_root: str | Path) -> None:
        self.log_root = Path(log_root)
        self.archive_dir = self.log_root / "archive"

    def files(self) -> tuple[Path, ...]:
        return tuple(_list_log_files(self.archive_dir))

    def files_for_range(
        self,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> tuple[Path, ...]:
        """按文件名日期缩小扫描集合。"""
        start_day = start.astimezone().date() if start is not None else None
        end_day = end.astimezone().date() if end is not None else None
        selected = []
        for path in self.files():
            day = _date_from_filename(path.name)
            if day is None:
                continue
            if start_day is not None and day < start_day:
                continue
            if end_day is not None and day > end_day:
                continue
            selected.append(path)
        return tuple(selected)

    def iter_records(self, files: Optional[Sequence[Path]] = None) -> Iterator[StoredLog]:
        for path in files or self.files():
            yield from self._iter_file(path)

    def iter_filtered(self, query: LogQuery) -> Iterator[StoredLog]:
        """流式返回匹配条件的记录，不缓存全部结果。"""
        files = self.files_for_range(query.start, query.end)
        for entry in self.iter_records(files):
            if _matches(entry, query):
                yield entry

    def _iter_file(self, path: Path) -> Iterator[StoredLog]:
        try:
            with open(path, "r", encoding="utf-8") as source:
                while True:
                    offset = source.tell()
                    line = source.readline()
                    if not line:
                        break
                    try:
                        payload = json.loads(line)
                        yield _payload_to_record(path.name, offset, payload)
                    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                        continue
        except OSError:
            return

    def query(self, query: LogQuery) -> LogPage:
        limit = max(1, query.limit)
        matched: deque[StoredLog] = deque(maxlen=limit)
        malformed = 0
        files = self.files_for_range(query.start, query.end)
        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as source:
                    while True:
                        offset = source.tell()
                        line = source.readline()
                        if not line:
                            break
                        try:
                            payload = json.loads(line)
                            entry = _payload_to_record(path.name, offset, payload)
                        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                            malformed += 1
                            continue
                        if _matches(entry, query):
                            matched.append(entry)
            except OSError:
                continue
        entries = list(matched)
        entries.sort(
            key=lambda item: (item.timestamp_utc_us, item.record_id),
            reverse=query.descending,
        )
        cursor = entries[-1].record_id if entries else None
        return LogPage(tuple(entries), len(files), malformed, cursor)

    def read_detail(self, record_id: str) -> Optional[StoredLog]:
        match = _PATH_PATTERN.match(record_id)
        if match is None:
            return None
        path = self.archive_dir / match.group("name")
        if not _is_safe_child(path, self.archive_dir):
            return None
        try:
            with open(path, "r", encoding="utf-8") as source:
                source.seek(int(match.group("offset")))
                payload = json.loads(source.readline())
            return _payload_to_record(path.name, int(match.group("offset")), payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
            return None

    def statistics(self, start: datetime, end: datetime) -> LogStatistics:
        counts: Counter[str] = Counter()
        trends: Dict[date, Counter[str]] = {}
        total = 0
        malformed = 0
        for path in self.files_for_range(start, end):
            try:
                with open(path, "r", encoding="utf-8") as source:
                    for line in source:
                        try:
                            entry = _payload_to_record(path.name, 0, json.loads(line))
                        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                            malformed += 1
                            continue
                        if not _in_range(entry.timestamp, start, end):
                            continue
                        total += 1
                        counts[entry.category] += 1
                        day_counts = trends.setdefault(
                            entry.timestamp.astimezone().date(),
                            Counter(),
                        )
                        day_counts[entry.category] += 1
            except OSError:
                continue
        points = tuple(
            LogTrendPoint(day, sum(values.values()), dict(values))
            for day, values in sorted(trends.items())
        )
        return LogStatistics(total, dict(counts), points, malformed)

    def aggregate_errors(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[Mapping[str, Any], ...]:
        groups: Dict[str, Dict[str, Any]] = {}
        query = LogQuery(
            levels=frozenset({"ERROR", "FATAL"}),
            start=start,
            end=end,
        )
        for entry in self.iter_filtered(query):
            fingerprint = entry.fingerprint or f"message:{entry.module}:{entry.message}"
            group = groups.setdefault(
                fingerprint,
                {
                    "fingerprint": fingerprint,
                    "count": 0,
                    "first_seen": entry.timestamp,
                    "last_seen": entry.timestamp,
                    "module": entry.module,
                    "message": entry.message,
                },
            )
            group["count"] += 1
            group["first_seen"] = min(group["first_seen"], entry.timestamp)
            group["last_seen"] = max(group["last_seen"], entry.timestamp)
        return tuple(
            sorted(
                groups.values(),
                key=lambda group: (-group["count"], group["fingerprint"]),
            )
        )


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "...<truncated>"


def _list_log_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        (path for path in directory.glob("app-*.jsonl") if path.is_file()),
        key=lambda path: (
            _date_from_filename(path.name) or date.min,
            _file_index(path.name),
        ),
    )


def _total_size(paths: Sequence[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _date_from_filename(name: str) -> Optional[date]:
    match = _DATE_PATTERN.match(name)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _file_index(name: str) -> int:
    match = _DATE_PATTERN.match(name)
    return int(match.group(2) or 0) if match else 0


def _is_safe_child(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve()) and not path.is_symlink()
    except OSError:
        return False


def _safe_unlink(path: Path, root: Path) -> bool:
    if not _is_safe_child(path, root):
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _payload_to_record(name: str, offset: int, payload: Mapping[str, Any]) -> StoredLog:
    timestamp_text = str(payload["timestamp"])
    timestamp = datetime.fromisoformat(timestamp_text)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    record_id = f"{name}:{offset}"
    return StoredLog(
        record_id=record_id,
        source_file=name,
        source_offset=offset,
        timestamp=timestamp,
        timestamp_utc_us=int(payload.get("timestamp_utc_us", _utc_microseconds(timestamp))),
        level=str(payload.get("level", "INFO")),
        category=str(payload.get("category", "INFO")),
        module=str(payload.get("module", "")),
        logger_name=str(payload.get("logger_name", "")),
        process_id=int(payload.get("process_id", 0)),
        thread_id=int(payload.get("thread_id", 0)),
        thread_name=str(payload.get("thread_name", "")),
        message=str(payload.get("message", "")),
        exception_type=_optional_text(payload.get("exception_type")),
        exception_message=_optional_text(payload.get("exception_message")),
        stack_trace=_optional_text(payload.get("stack_trace")),
        extra=payload.get("extra", {}) if isinstance(payload.get("extra", {}), Mapping) else {},
        fingerprint=_optional_text(payload.get("fingerprint")),
    )


def _optional_text(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def stored_to_payload(entry: StoredLog) -> Dict[str, Any]:
    """将查询结果转换为可导出的 JSON 对象。"""
    return {
        "schema_version": 1,
        "timestamp": entry.timestamp.isoformat(),
        "timestamp_utc_us": entry.timestamp_utc_us,
        "level": entry.level,
        "category": entry.category,
        "module": entry.module,
        "logger_name": entry.logger_name,
        "process_id": entry.process_id,
        "thread_id": entry.thread_id,
        "thread_name": entry.thread_name,
        "message": entry.message,
        "exception_type": entry.exception_type,
        "exception_message": entry.exception_message,
        "stack_trace": entry.stack_trace,
        "extra": _safe_json_value(entry.extra),
        "fingerprint": entry.fingerprint,
    }


def _matches(entry: StoredLog, query: LogQuery) -> bool:
    if query.levels and not ({entry.category, entry.level} & query.levels):
        return False
    if query.start is not None and entry.timestamp < query.start:
        return False
    if query.end is not None and entry.timestamp >= query.end:
        return False
    if query.module and query.module.lower() not in entry.module.lower():
        return False
    if query.keyword:
        haystack = " ".join(
            (
                entry.message,
                entry.module,
                entry.logger_name,
                entry.exception_message or "",
                entry.stack_trace or "",
            )
        ).lower()
        if query.keyword.lower() not in haystack:
            return False
    return True


def _in_range(value: datetime, start: datetime, end: datetime) -> bool:
    return value >= start and value < end


__all__ = [
    "DailyJsonlHandler", "JsonlLogStore", "LogPage", "LogQuery", "LogStatistics",
    "LogTrendPoint", "StoredLog", "compute_fingerprint", "record_to_payload",
    "stored_to_payload",
]

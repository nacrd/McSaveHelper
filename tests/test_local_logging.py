"""Tests for the standard logging bridge and local JSONL storage."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app.services.log_query_service import LogExportService
from core.logging.handlers import LogHandler
from core.logging.manager import LogManager
from core.logging.models import LogLevel, LogRecord
from core.logging.storage import DailyJsonlHandler, JsonlLogStore, LogQuery


class _CollectingHandler(LogHandler):
    def __init__(self) -> None:
        super().__init__(LogLevel.DEBUG)
        self.records: list[LogRecord] = []

    def handle(self, record: LogRecord) -> None:
        self.records.append(record)


def test_stdlib_bridge_preserves_extra_and_exception() -> None:
    LogManager._instance = None
    manager = LogManager()
    collector = _CollectingHandler()
    manager.add_handler(collector)
    manager.set_level(LogLevel.DEBUG)
    manager.install_stdlib_bridge()

    logging.getLogger("test.external").info("value=%s", 3, extra={"request_id": "r1"})
    try:
        raise ValueError("bad value")
    except ValueError:
        manager.error("operation failed", module="Test", exc_info=True)

    manager.flush()
    assert [record.message for record in collector.records] == [
        "value=3",
        "operation failed",
    ]
    assert collector.records[0].extra["request_id"] == "r1"
    assert collector.records[1].exception_type == "ValueError"
    assert collector.records[1].stack_trace and "bad value" in collector.records[1].stack_trace
    manager.shutdown()
    LogManager._instance = None


def test_jsonl_rotation_query_and_statistics(tmp_path: Path) -> None:
    handler = DailyJsonlHandler(tmp_path, max_file_size=500, level=LogLevel.DEBUG)
    now = datetime.now().astimezone()
    for index in range(8):
        handler.handle(
            LogRecord(
                timestamp=now + timedelta(seconds=index),
                level=LogLevel.ERROR if index % 2 else LogLevel.INFO,
                message=f"message-{index}",
                module="Storage",
                thread_id=1,
                thread_name="test",
            )
        )
    handler.close()

    store = JsonlLogStore(tmp_path)
    assert len(store.files()) > 1
    page = store.query(LogQuery(levels=frozenset({"ERROR"}), limit=20))
    assert [entry.message for entry in page.entries] == [
        "message-7", "message-5", "message-3", "message-1"
    ]
    statistics = store.statistics(now - timedelta(minutes=1), now + timedelta(minutes=1))
    assert statistics.total == 8
    assert statistics.by_category == {"INFO": 4, "ERROR": 4}


def test_jsonl_query_reports_malformed_lines(tmp_path: Path) -> None:
    handler = DailyJsonlHandler(tmp_path)
    handler.handle(LogRecord(datetime.now().astimezone(), LogLevel.INFO, "valid"))
    handler.close()
    path = JsonlLogStore(tmp_path).files()[0]
    with path.open("a", encoding="utf-8") as output:
        output.write("not-json\n")

    page = JsonlLogStore(tmp_path).query(LogQuery(limit=10))
    assert [entry.message for entry in page.entries] == ["valid"]
    assert page.malformed_lines == 1


def test_print_redirect_is_reversible() -> None:
    LogManager._instance = None
    manager = LogManager()
    collector = _CollectingHandler()
    manager.add_handler(collector)
    original_stdout = sys.stdout

    manager.install_stream_redirects()
    print("captured output")
    manager.remove_stream_redirects()
    manager.flush()

    assert sys.stdout is original_stdout
    assert [(record.module, record.message) for record in collector.records] == [
        ("stdout", "captured output")
    ]
    manager.shutdown()
    LogManager._instance = None


def test_clear_archives_allows_subsequent_writes(tmp_path: Path) -> None:
    handler = DailyJsonlHandler(tmp_path)
    now = datetime.now().astimezone()
    handler.handle(LogRecord(now, LogLevel.INFO, "before"))

    assert handler.clear_archives() == 1
    handler.handle(LogRecord(now, LogLevel.INFO, "after"))
    handler.close()

    page = JsonlLogStore(tmp_path).query(LogQuery(limit=10))
    assert [entry.message for entry in page.entries] == ["after"]


def test_runtime_capacity_limit_prunes_rotated_archives(tmp_path: Path) -> None:
    handler = DailyJsonlHandler(
        tmp_path,
        max_file_size=700,
        max_total_bytes=1_400,
        level=LogLevel.DEBUG,
    )
    now = datetime.now().astimezone()

    for index in range(20):
        handler.handle(LogRecord(now, LogLevel.INFO, f"message-{index}-" + "x" * 80))

    handler.close()
    files = JsonlLogStore(tmp_path).files()
    assert len(files) < 20
    assert sum(path.stat().st_size for path in files) <= 1_400


def test_runtime_capacity_warning_when_active_file_exceeds_limit(tmp_path: Path) -> None:
    statuses: list[str] = []
    handler = DailyJsonlHandler(
        tmp_path,
        max_file_size=10_000,
        max_total_bytes=300,
        status_callback=statuses.append,
    )

    handler.handle(
        LogRecord(datetime.now().astimezone(), LogLevel.INFO, "x" * 500)
    )

    assert statuses == ["storage_full"]
    handler.close()


def test_shutdown_drains_queue_and_restores_root_level() -> None:
    LogManager._instance = None
    manager = LogManager()
    collector = _CollectingHandler()
    manager.add_handler(collector)
    manager.set_level(LogLevel.DEBUG)
    root_logger = logging.getLogger()
    original_level = root_logger.level
    manager.install_stdlib_bridge()

    for index in range(100):
        manager.info(f"queued-{index}", module="Shutdown")
    manager.shutdown()

    assert len(collector.records) == 100
    assert root_logger.level == original_level
    LogManager._instance = None


def test_daily_rotation_and_retention_remove_expired_archive(tmp_path: Path) -> None:
    current = datetime.now().astimezone()
    old = current - timedelta(days=5)
    handler = DailyJsonlHandler(
        tmp_path,
        retention_days=2,
        clock=lambda: current,
    )

    handler.handle(LogRecord(old, LogLevel.INFO, "expired"))
    handler.handle(LogRecord(current, LogLevel.INFO, "current"))
    handler.close()

    files = JsonlLogStore(tmp_path).files()
    assert [path.name for path in files] == [f"app-{current.date().isoformat()}.jsonl"]


def test_query_combines_time_level_keyword_and_module_filters(tmp_path: Path) -> None:
    now = datetime.now().astimezone()
    handler = DailyJsonlHandler(tmp_path)
    records = (
        LogRecord(now - timedelta(minutes=3), LogLevel.ERROR, "disk full", "Backup"),
        LogRecord(now - timedelta(minutes=2), LogLevel.ERROR, "disk full", "Migration"),
        LogRecord(now - timedelta(minutes=1), LogLevel.INFO, "disk full", "Backup"),
    )
    for record in records:
        handler.handle(record)
    handler.close()

    page = JsonlLogStore(tmp_path).query(LogQuery(
        levels=frozenset({"ERROR"}),
        start=now - timedelta(minutes=4),
        end=now,
        keyword="FULL",
        module="back",
        limit=10,
    ))

    assert [(entry.module, entry.message) for entry in page.entries] == [
        ("Backup", "disk full")
    ]


def test_error_aggregation_normalizes_variable_numbers(tmp_path: Path) -> None:
    now = datetime.now().astimezone()
    handler = DailyJsonlHandler(tmp_path)
    for value in (123, 456):
        handler.handle(LogRecord(
            now,
            LogLevel.ERROR,
            f"failed to load chunk {value}",
            "Region",
        ))
    handler.close()

    groups = JsonlLogStore(tmp_path).aggregate_errors(
        now - timedelta(minutes=1),
        now + timedelta(minutes=1),
    )

    assert len(groups) == 1
    assert groups[0]["count"] == 2


def test_export_writes_only_current_filter_results(tmp_path: Path) -> None:
    now = datetime.now().astimezone()
    handler = DailyJsonlHandler(tmp_path / "source")
    handler.handle(LogRecord(now, LogLevel.INFO, "keep", "Export"))
    handler.handle(LogRecord(now, LogLevel.ERROR, "skip", "Export"))
    handler.close()
    destination = tmp_path / "result.jsonl"

    count = LogExportService(JsonlLogStore(tmp_path / "source")).export_jsonl(
        LogQuery(levels=frozenset({"INFO"})),
        destination,
    )

    payloads = [
        json.loads(line)
        for line in destination.read_text(encoding="utf-8").splitlines()
    ]
    assert count == 1
    assert [payload["message"] for payload in payloads] == ["keep"]

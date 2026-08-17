"""Application services for querying and exporting local JSONL logs."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from core.logging.storage import (
    JsonlLogStore,
    LogPage,
    LogQuery,
    LogStatistics,
    StoredLog,
    stored_to_payload,
)


class LogQueryService:
    """协调日志查询、详情、统计和异常聚合的应用端口。"""

    def __init__(self, store: JsonlLogStore) -> None:
        self._store = store

    def query(self, query: LogQuery) -> LogPage:
        """执行一页日志查询。

        Args:
            query: 级别、时间、关键词和模块条件。

        Returns:
            后台任务可直接返回给 controller 的不可变结果。
        """
        return self._store.query(query)

    def get_detail(self, record_id: str) -> Optional[StoredLog]:
        """按文件名和字节偏移读取一条完整日志。"""
        return self._store.read_detail(record_id)

    def statistics(self, start: datetime, end: datetime) -> LogStatistics:
        """计算时间范围内的总量、级别分布和日趋势。"""
        return self._store.statistics(start, end)

    def aggregate_errors(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[Mapping[str, object], ...]:
        """按异常指纹聚合错误。"""
        return self._store.aggregate_errors(start, end)


class LogExportService:
    """将当前筛选条件流式导出为 JSONL。"""

    def __init__(self, store: JsonlLogStore) -> None:
        self._store = store

    def export_jsonl(self, query: LogQuery, destination: str | Path) -> int:
        """原子写入筛选结果并返回导出条数。"""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temp_path = Path(output.name)
                for entry in self._store.iter_filtered(query):
                    output.write(json.dumps(stored_to_payload(entry), ensure_ascii=False))
                    output.write("\n")
                    count += 1
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, target)
            temp_path = None
            return count
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


__all__ = ["LogExportService", "LogQueryService"]

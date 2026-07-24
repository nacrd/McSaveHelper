"""应用级有界操作指标存储。"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import replace
from types import MappingProxyType
from typing import Optional
from uuid import uuid4

from core.observability import (
    OperationOutcome,
    OperationRecord,
    metrics_to_operation_record,
)
from core.performance import PerformanceMetrics


class OperationMetricsStore:
    """线程安全地保留最近的统一操作记录。"""

    def __init__(self, max_records: int = 1000) -> None:
        """创建固定容量的记录队列。

        Args:
            max_records: 最多保留的操作记录数。

        Raises:
            ValueError: 容量小于一。
        """
        if max_records < 1:
            raise ValueError("操作指标容量必须至少为 1")
        self._max_records = max_records
        self._records: deque[OperationRecord] = deque(maxlen=max_records)
        self._lock = threading.Lock()

    @property
    def max_records(self) -> int:
        """返回固定记录容量。"""
        return self._max_records

    @property
    def record_count(self) -> int:
        """返回当前保留的记录数。"""
        with self._lock:
            return len(self._records)

    def record(self, record: OperationRecord) -> None:
        """保存一份不可变 metadata 快照。

        Args:
            record: 已符合统一观测协议的操作记录。
        """
        stored = replace(
            record,
            metadata=MappingProxyType(dict(record.metadata)),
        )
        with self._lock:
            self._records.append(stored)

    def record_metrics(
        self,
        metrics: PerformanceMetrics,
        *,
        feature: str = "business",
        world_id: str = "",
    ) -> OperationRecord:
        """转换并保存一次业务性能指标。

        Args:
            metrics: ``core.performance`` 完成的业务指标。
            feature: 操作所属功能域。
            world_id: 可选世界身份。

        Returns:
            已分配唯一 ID 的统一操作记录。
        """
        base = metrics_to_operation_record(
            metrics,
            feature=feature,
            world_id=world_id,
        )
        metadata = dict(base.metadata)
        metadata.setdefault("operation", base.operation_id)
        record = replace(
            base,
            operation_id=uuid4().hex,
            metadata=metadata,
        )
        self.record(record)
        return record

    def snapshot(
        self,
        *,
        feature: Optional[str] = None,
        world_id: Optional[str] = None,
        outcome: Optional[OperationOutcome] = None,
        limit: Optional[int] = None,
    ) -> tuple[OperationRecord, ...]:
        """返回按条件过滤的时间顺序快照。

        Args:
            feature: 可选功能域过滤器。
            world_id: 可选世界身份过滤器。
            outcome: 可选终态过滤器。
            limit: 仅返回最后若干条；None 返回全部。

        Returns:
            从旧到新排列的记录元组。

        Raises:
            ValueError: limit 小于零。
        """
        if limit is not None and limit < 0:
            raise ValueError("操作指标查询数量不能为负数")
        with self._lock:
            records = tuple(self._records)
        selected = tuple(
            record
            for record in records
            if (feature is None or record.feature == feature)
            and (world_id is None or record.world_id == world_id)
            and (outcome is None or record.outcome is outcome)
        )
        if limit is None:
            return selected
        if limit == 0:
            return ()
        return selected[-limit:]

    def clear(self) -> None:
        """清除全部已保留记录。"""
        with self._lock:
            self._records.clear()


__all__ = ["OperationMetricsStore"]

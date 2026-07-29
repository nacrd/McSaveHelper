"""统一操作指标协议：业务与 UI 共用同一条观测记录。

UI 适配器（``app.ui.performance``）只负责展示与告警，不另起一套
业务语义。core 与 app.services 只发布 ``OperationRecord`` /
``PerformanceMetrics``，由 sink 投递到 UI 或日志。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class OperationOutcome(str, Enum):
    """操作终态分类。"""

    OK = "ok"
    CANCELLED = "cancelled"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True)
class OperationRecord:
    """一次后台或业务操作的统一指标快照。

    Attributes:
        operation_id: 单次操作唯一标识；稳定操作名放在 metadata。
        feature: 功能域，如 map / migration / stats。
        world_id: 可选世界路径或短哈希；无世界上下文时为空。
        queue_wait_ms: 进入队列到开始执行的等待毫秒。
        run_ms: 实际执行毫秒。
        files_processed: 处理的文件数。
        bytes_processed: 处理的字节数。
        cache_hits: 缓存命中次数。
        cache_misses: 缓存未命中次数。
        outcome: 终态。
        metadata: 额外键值（不得包含密钥或超大 NBT）。
    """

    operation_id: str
    feature: str
    world_id: str = ""
    queue_wait_ms: float = 0.0
    run_ms: float = 0.0
    files_processed: int = 0
    bytes_processed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    outcome: OperationOutcome = OperationOutcome.OK
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化字典。"""
        return {
            "operation_id": self.operation_id,
            "feature": self.feature,
            "world_id": self.world_id,
            "queue_wait_ms": round(self.queue_wait_ms, 3),
            "run_ms": round(self.run_ms, 3),
            "files_processed": self.files_processed,
            "bytes_processed": self.bytes_processed,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "outcome": self.outcome.value,
            "metadata": dict(self.metadata),
        }


def metrics_to_operation_record(
    metrics: Any,
    *,
    feature: str = "business",
    world_id: str = "",
    outcome: OperationOutcome = OperationOutcome.OK,
    queue_wait_ms: float = 0.0,
) -> OperationRecord:
    """将 ``PerformanceMetrics`` 适配为统一 ``OperationRecord``。

    Args:
        metrics: ``core.performance.PerformanceMetrics`` 实例。
        feature: 功能域标签。
        world_id: 可选世界标识。
        outcome: 终态。
        queue_wait_ms: 队列等待；未知时为 0。
    """
    metadata = dict(getattr(metrics, "metadata", {}) or {})
    errors = int(getattr(metrics, "errors", 0) or 0)
    selected_outcome = outcome
    if errors > 0 and selected_outcome is OperationOutcome.OK:
        selected_outcome = OperationOutcome.ERROR
    return OperationRecord(
        operation_id=str(getattr(metrics, "operation", "unknown")),
        feature=feature,
        world_id=world_id or str(metadata.get("world_id", "") or ""),
        queue_wait_ms=float(queue_wait_ms),
        run_ms=float(getattr(metrics, "duration_seconds", 0.0) or 0.0) * 1000.0,
        files_processed=int(getattr(metrics, "files_processed", 0) or 0),
        bytes_processed=int(getattr(metrics, "bytes_processed", 0) or 0),
        cache_hits=int(metadata.get("cache_hits", 0) or 0),
        cache_misses=int(metadata.get("cache_misses", 0) or 0),
        outcome=selected_outcome,
        metadata=metadata,
    )


def percentile(samples: list[float], ratio: float) -> float:
    """计算样本分位数；空列表返回 0。

    Args:
        samples: 数值样本（毫秒等）。
        ratio: 0..1 分位，例如 0.95。
    """
    if not samples:
        return 0.0
    if ratio <= 0:
        return float(min(samples))
    if ratio >= 1:
        return float(max(samples))
    ordered = sorted(float(item) for item in samples)
    # Nearest-rank percentile (inclusive).
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return ordered[index]


def p95(samples: list[float]) -> float:
    """返回样本 p95。"""
    return percentile(samples, 0.95)


__all__ = [
    "OperationOutcome",
    "OperationRecord",
    "metrics_to_operation_record",
    "p95",
    "percentile",
]

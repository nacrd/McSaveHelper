"""区域删除用例：通过共享运行时和世界事务异步执行。"""
from __future__ import annotations

import threading
from concurrent.futures import CancelledError
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from app.services.execution_runtime import (
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)
from app.services.region_editor_service import delete_region_via_transaction
from app.services.world_transaction import (
    WorldTransactionCancelledError,
    WorldTransactionResult,
    WorldTransactionService,
)


class RegionDeleteBusyError(RuntimeError):
    """当前控制器已有区域删除任务时抛出。"""


class RegionDeleteStatus(str, Enum):
    """区域删除后台任务的终态。"""

    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class RegionDeleteRequest:
    """区域删除所需的不可变输入与视图身份。"""

    world_path: Path
    region_path: Path
    coord: tuple[int, int]
    generation: int


@dataclass(frozen=True)
class RegionDeleteOutcome:
    """供 UI 线程投影的区域删除终态。"""

    request: RegionDeleteRequest
    status: RegionDeleteStatus
    result: Optional[WorldTransactionResult[bool]] = None
    error: Optional[Exception] = None


RegionDeleteCallback = Callable[[RegionDeleteOutcome], None]


class RegionDeleteController:
    """拥有单个区域删除任务，并把终态发布给调用方。"""

    def __init__(
        self,
        scope: OperationScope,
        world_transactions: WorldTransactionService,
    ) -> None:
        """注入 Explorer 任务作用域和共享世界事务端口。"""
        self._scope = scope
        self._world_transactions = world_transactions
        self._lock = threading.Lock()
        self._active: Optional[OperationHandle[
            WorldTransactionResult[bool]
        ]] = None

    @property
    def is_running(self) -> bool:
        """返回是否仍有未发布终态的删除任务。"""
        with self._lock:
            return self._active is not None

    def start(
        self,
        request: RegionDeleteRequest,
        callback: RegionDeleteCallback,
    ) -> OperationHandle[WorldTransactionResult[bool]]:
        """非阻塞提交区域删除任务。

        Raises:
            RegionDeleteBusyError: 已有删除任务尚未结束。
            RuntimeClosedError: Explorer 作用域已经关闭。
            TaskQueueFullError: I/O 通道达到容量上限。
        """
        with self._lock:
            if self._active is not None:
                raise RegionDeleteBusyError("已有区域删除任务正在执行")
            handle = self._scope.submit(
                "delete_region",
                lambda token: delete_region_via_transaction(
                    self._world_transactions,
                    request.world_path,
                    request.region_path,
                    backup_label="删除区域前自动备份",
                    cancel_check=lambda: token.is_cancelled,
                ),
                priority=TaskPriority.INTERACTIVE,
            )
            self._active = handle
        handle.add_done_callback(
            lambda completed: self._complete(completed, request, callback)
        )
        return handle

    def cancel(self) -> bool:
        """请求取消当前区域删除任务。"""
        with self._lock:
            handle = self._active
        return handle.cancel() if handle is not None else False

    def _complete(
        self,
        handle: OperationHandle[WorldTransactionResult[bool]],
        request: RegionDeleteRequest,
        callback: RegionDeleteCallback,
    ) -> None:
        """把 Future 的结果或异常转换为结构化终态。"""
        outcome = self._build_outcome(handle, request)
        with self._lock:
            if self._active is handle:
                self._active = None
        callback(outcome)

    @staticmethod
    def _build_outcome(
        handle: OperationHandle[WorldTransactionResult[bool]],
        request: RegionDeleteRequest,
    ) -> RegionDeleteOutcome:
        """读取已结束任务且保留取消与失败语义。"""
        try:
            result = handle.result()
        except (
            CancelledError,
            OperationCancelledError,
            WorldTransactionCancelledError,
        ) as exc:
            return RegionDeleteOutcome(
                request=request,
                status=RegionDeleteStatus.CANCELLED,
                error=exc,
            )
        except Exception as exc:
            if handle.cancelled:
                return RegionDeleteOutcome(
                    request=request,
                    status=RegionDeleteStatus.CANCELLED,
                    error=exc,
                )
            return RegionDeleteOutcome(
                request=request,
                status=RegionDeleteStatus.FAILED,
                error=exc,
            )
        return RegionDeleteOutcome(
            request=request,
            status=RegionDeleteStatus.SUCCEEDED,
            result=result,
        )


__all__ = [
    "RegionDeleteBusyError",
    "RegionDeleteController",
    "RegionDeleteOutcome",
    "RegionDeleteRequest",
    "RegionDeleteStatus",
]

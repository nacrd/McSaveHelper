"""Explorer NBT 后台 I/O 的完成协调与生命周期边界。"""
from __future__ import annotations

from concurrent.futures import CancelledError
from threading import Lock
from typing import Callable, Optional, TypeVar

import flet as ft

from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationCancelledError,
    OperationHandle,
    OperationScope,
    TaskPriority,
)
from app.ui.utils import run_on_ui
from core.omni.world_session import WorldSession


ResultT = TypeVar("ResultT")
ErrorCallback = Callable[[Exception, str], None]
RequestGuard = Callable[[], bool]


class NbtIoCoordinator:
    """把 NBT 文件操作提交到共享 I/O lane，并抑制迟到回调。"""

    def __init__(
        self,
        *,
        task_scope: Optional[OperationScope],
        page: Optional[ft.Page],
        get_world_session: Callable[[], Optional[WorldSession]],
        handle_error: ErrorCallback,
    ) -> None:
        """绑定 Explorer 共享任务作用域和最小 UI 端口。

        Args:
            task_scope: Explorer 拥有的共享任务作用域；None 用于轻量测试。
            page: Flet 页面；None 时在调用线程直接投影结果。
            get_world_session: 当前世界会话获取器。
            handle_error: 默认错误处理回调。
        """
        self._task_scope = task_scope
        self._page = page
        self._get_world_session = get_world_session
        self._handle_error = handle_error
        self._lock = Lock()
        self._closed = False

    def submit(
        self,
        operation: str,
        work: Callable[[Optional[CancellationToken]], ResultT],
        on_success: Callable[[ResultT], None],
        error_title: str,
        *,
        session: Optional[WorldSession] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        request_guard: Optional[RequestGuard] = None,
    ) -> None:
        """提交 I/O，并在 UI 真正消费前复查关闭、会话和请求身份。

        Args:
            operation: 运行时观测使用的操作名。
            work: 接收取消令牌的后台工作。
            on_success: UI 线程成功回调。
            error_title: 默认错误处理标题。
            session: 操作发起时的世界会话身份。
            on_error: 可选的定制错误回调。
            request_guard: UI 消费前复查 generation 的函数。
        """
        if not self._is_deliverable(session, request_guard):
            return
        scope = self._task_scope
        if scope is None:
            self._run_inline(
                work,
                on_success,
                error_title,
                session,
                on_error,
                request_guard,
            )
            return
        try:
            handle = scope.submit(
                operation,
                work,
                lane=ExecutionLane.IO,
                priority=TaskPriority.INTERACTIVE,
            )
            handle.add_done_callback(
                lambda completed: self._finish(
                    completed,
                    on_success,
                    error_title,
                    session,
                    on_error,
                    request_guard,
                )
            )
        except Exception as error:
            self._post_error(
                error,
                error_title,
                session,
                on_error,
                request_guard,
            )

    def close(self) -> None:
        """使已排队的 UI 回调失效；共享任务作用域仍由 Explorer 关闭。"""
        with self._lock:
            self._closed = True

    def _run_inline(
        self,
        work: Callable[[Optional[CancellationToken]], ResultT],
        on_success: Callable[[ResultT], None],
        error_title: str,
        session: Optional[WorldSession],
        on_error: Optional[Callable[[Exception], None]],
        request_guard: Optional[RequestGuard],
    ) -> None:
        """保留无运行时测试环境的同步执行行为。"""
        try:
            result = work(None)
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_error(
                error,
                error_title,
                session,
                on_error,
                request_guard,
            )
            return
        self._post_to_ui(
            on_success,
            result,
            session=session,
            request_guard=request_guard,
        )

    def _finish(
        self,
        handle: OperationHandle[ResultT],
        on_success: Callable[[ResultT], None],
        error_title: str,
        session: Optional[WorldSession],
        on_error: Optional[Callable[[Exception], None]],
        request_guard: Optional[RequestGuard],
    ) -> None:
        """读取后台终态并把成功或失败投递给 UI。"""
        if handle.cancelled:
            return
        try:
            result = handle.result()
        except (CancelledError, OperationCancelledError):
            return
        except Exception as error:
            self._post_error(
                error,
                error_title,
                session,
                on_error,
                request_guard,
            )
            return
        self._post_to_ui(
            on_success,
            result,
            session=session,
            request_guard=request_guard,
        )

    def _post_error(
        self,
        error: Exception,
        error_title: str,
        session: Optional[WorldSession],
        on_error: Optional[Callable[[Exception], None]],
        request_guard: Optional[RequestGuard],
    ) -> None:
        """按定制或默认签名投递 I/O 错误。"""
        if on_error is None:
            self._post_to_ui(
                self._handle_error,
                error,
                error_title,
                session=session,
                request_guard=request_guard,
            )
            return
        self._post_to_ui(
            on_error,
            error,
            session=session,
            request_guard=request_guard,
        )

    def _post_to_ui(
        self,
        callback: Callable[..., object],
        *args: object,
        session: Optional[WorldSession] = None,
        request_guard: Optional[RequestGuard] = None,
    ) -> None:
        """投递带二次身份检查的 UI 回调。"""
        def guarded() -> None:
            if self._is_deliverable(session, request_guard):
                callback(*args)

        if self._page is None:
            guarded()
            return
        run_on_ui(self._page, guarded)

    def _is_deliverable(
        self,
        session: Optional[WorldSession],
        request_guard: Optional[RequestGuard],
    ) -> bool:
        """检查协调器、世界会话及 loader generation 是否仍有效。"""
        with self._lock:
            if self._closed:
                return False
        if session is not None and self._get_world_session() is not session:
            return False
        return request_guard is None or request_guard()

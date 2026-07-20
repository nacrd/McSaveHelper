"""UI 公共工具函数"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future as ConcurrentFuture
from typing import Any, Callable, Coroutine, Optional

import flet as ft

# 全局关闭标记，防止关闭过程中触发 UI 更新
_app_closing = False
ScheduledTask = asyncio.Future[Any] | ConcurrentFuture[Any]


def is_app_closing() -> bool:
    """检查应用是否正在关闭"""
    return _app_closing


def set_app_closing(closing: bool) -> None:
    """设置应用关闭状态"""
    global _app_closing
    _app_closing = closing


def is_control_update_error(exc: BaseException) -> bool:
    """Whether *exc* is a known Flet unmounted/teardown update failure."""
    if isinstance(exc, RuntimeError):
        return True
    # Flet/desktop hosts occasionally raise AssertionError or AttributeError
    # when a control is disposed mid-update.
    if isinstance(exc, (AssertionError, AttributeError)):
        return True
    text = str(exc).lower()
    markers = (
        "must be added to the page first",
        "control must be added",
        "not on page",
        "has no attribute",
        "closed",
        "disposed",
    )
    return any(marker in text for marker in markers)


def safe_update(control: ft.Control) -> bool:
    """安全更新控件。

    若应用正在关闭，或控件未挂载/已卸载，静默跳过。

    Returns:
        bool: 是否成功调用 ``control.update()``。
    """
    if _app_closing:
        return False
    try:
        control.update()
        return True
    except Exception as exc:
        if is_control_update_error(exc):
            return False
        # Unexpected errors still should not crash UI event handlers.
        return False


def run_on_ui(
    page: ft.Page | None,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    """在 Flet UI 线程上执行回调；页面不可用时安全跳过。

    Flet 控件更新必须尽量在 UI 线程中完成。后台线程、Timer 或服务回调
    调用 GUI 代码时统一走此 helper，避免散落的 ``page.run_task`` 样板。
    """
    if _app_closing or page is None:
        return

    async def _runner() -> None:
        if _app_closing:
            return
        try:
            func(*args, **kwargs)
        except Exception as exc:
            # Callback itself may touch unmounted controls.
            if not is_control_update_error(exc):
                # Keep silent for UI best-effort; callers that need logging
                # should wrap their own logic.
                return

    try:
        page.run_task(_runner)
    except Exception as exc:
        if not is_control_update_error(exc):
            return


def schedule_coroutine(
    coroutine: Coroutine[Any, Any, Any],
    *,
    page: Optional[ft.Page] = None,
) -> Optional[ScheduledTask]:
    """Schedule a coroutine on the active loop, Flet page, or worker loop."""
    try:
        return asyncio.get_running_loop().create_task(coroutine)
    except RuntimeError:
        pass

    if page is not None:
        try:
            async def _runner() -> Any:
                return await coroutine

            return page.run_task(_runner)
        except Exception as exc:
            if not is_control_update_error(exc):
                pass

    def _run_in_thread() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coroutine)
        finally:
            loop.close()

    threading.Thread(target=_run_in_thread, daemon=True).start()
    return None


def format_size(size: int) -> str:
    """格式化文件大小为人类可读的字符串

    Args:
        size: 文件大小（字节）

    Returns:
        格式化后的字符串，如 "1.5 MB"、"300 KB"、"512 B"
    """
    kb = size / 1024
    mb = kb / 1024
    gb = mb / 1024
    if gb >= 1:
        return f"{gb:.2f} GB"
    if mb >= 1:
        return f"{mb:.1f} MB"
    if kb >= 1:
        return f"{kb:.1f} KB"
    return f"{size} B"

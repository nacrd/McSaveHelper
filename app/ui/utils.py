"""UI 公共工具函数"""
from typing import Any, Callable

import flet as ft

# 全局关闭标记，防止关闭过程中触发 UI 更新
_app_closing = False


def is_app_closing() -> bool:
    """检查应用是否正在关闭"""
    return _app_closing


def set_app_closing(closing: bool) -> None:
    """设置应用关闭状态"""
    global _app_closing
    _app_closing = closing


def safe_update(control: ft.Control) -> None:
    """安全更新控件，若控件未挂载到页面或正在关闭则静默跳过"""
    if _app_closing:
        return
    try:
        control.update()
    except RuntimeError:
        pass


def run_on_ui(page: ft.Page | None,
              func: Callable[...,
                             Any],
              *args: Any,
              **kwargs: Any) -> None:
    """在 Flet UI 线程上执行回调；页面不可用时安全跳过。

    Flet 控件更新必须尽量在 UI 线程中完成。后台线程、Timer 或服务回调
    调用 GUI 代码时统一走此 helper，避免散落的 ``page.run_task`` 样板。
    """
    if _app_closing or page is None:
        return

    async def _runner() -> None:
        if _app_closing:
            return
        func(*args, **kwargs)

    try:
        page.run_task(_runner)
    except Exception:
        pass


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

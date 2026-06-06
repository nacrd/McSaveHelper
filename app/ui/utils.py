"""UI 公共工具函数"""
import flet as ft


def safe_update(control: ft.Control) -> None:
    """安全更新控件，若控件未挂载到页面则静默跳过"""
    try:
        control.update()
    except RuntimeError:
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

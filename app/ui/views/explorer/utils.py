"""Explorer utilities"""
import flet as ft


def safe_update(control: ft.Control) -> None:
    """安全更新控件，若控件未挂载到页面则静默跳过"""
    try:
        control.update()
    except RuntimeError:
        pass
"""Flet 对统一 UI 投递通道的薄适配。"""
from __future__ import annotations

from typing import Callable

import flet as ft

from app.services.ui_delivery import UiDeliveryChannel
from app.ui.utils import schedule_on_ui
from core.observability import OperationRecord


def create_ui_delivery(
    page: ft.Page,
    operation_sink: Callable[[OperationRecord], None],
) -> UiDeliveryChannel:
    """创建只负责调度到给定 Flet 页面的 UI 投递通道。

    Args:
        page: 应用页面。
        operation_sink: 应用级统一操作记录接收器。

    Returns:
        不向 service 层泄漏 Flet 类型的投递通道。
    """
    return UiDeliveryChannel(
        lambda callback: schedule_on_ui(page, callback),
        operation_sink,
    )


__all__ = ["create_ui_delivery"]

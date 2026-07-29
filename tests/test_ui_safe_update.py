"""Tests for UI safe_update helpers."""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import cast

import flet as ft

from app.ui.utils import (
    is_control_update_error,
    safe_update,
    schedule_coroutine,
    schedule_on_ui,
    set_app_closing,
)


def test_is_control_update_error_recognizes_runtime_and_markers() -> None:
    assert is_control_update_error(RuntimeError("must be added to the page first"))
    assert is_control_update_error(AssertionError("control disposed"))
    assert is_control_update_error(AttributeError("object has no attribute 'page'"))
    assert not is_control_update_error(ValueError("bad value"))


def test_safe_update_skips_when_closing_and_swallows_unmounted() -> None:
    set_app_closing(True)
    try:
        calls = {"n": 0}

        def update() -> None:
            calls["n"] += 1

        control = SimpleNamespace(update=update)
        assert safe_update(control) is False  # type: ignore[arg-type]
        assert calls["n"] == 0
    finally:
        set_app_closing(False)

    def boom() -> None:
        raise RuntimeError("Control must be added to the page first")

    assert safe_update(SimpleNamespace(update=boom)) is False  # type: ignore[arg-type]

    def ok() -> None:
        return None

    assert safe_update(SimpleNamespace(update=ok)) is True  # type: ignore[arg-type]


def test_schedule_on_ui_reports_acceptance_and_runs_callback() -> None:
    observed: list[str] = []

    def run_task(factory) -> None:
        asyncio.run(factory())

    page = SimpleNamespace(run_task=run_task)

    assert schedule_on_ui(
        page,  # type: ignore[arg-type]
        lambda: observed.append("delivered"),
    ) is True
    assert observed == ["delivered"]

    set_app_closing(True)
    try:
        assert schedule_on_ui(page, lambda: None) is False  # type: ignore[arg-type]
    finally:
        set_app_closing(False)


def test_schedule_coroutine_without_ui_loop_closes_coroutine() -> None:
    async def pending() -> None:
        await asyncio.sleep(0)

    coroutine = pending()

    assert schedule_coroutine(coroutine) is None
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED


def test_schedule_coroutine_closes_after_page_rejects_task() -> None:
    async def pending() -> None:
        await asyncio.sleep(0)

    page = cast(
        ft.Page,
        SimpleNamespace(
            run_task=lambda _factory: (_ for _ in ()).throw(
                RuntimeError("page closed")
            ),
        ),
    )
    coroutine = pending()

    assert schedule_coroutine(coroutine, page=page) is None
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED

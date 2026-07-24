import asyncio
from concurrent.futures import Future

from app.ui.delayed_scheduler import UiDelayedScheduler


class _Page:
    def __init__(self):
        self.handlers = []

    def run_task(self, handler):
        self.handlers.append(handler)
        return Future()


def test_ui_delayed_scheduler_runs_callback_once_on_page_loop() -> None:
    page = _Page()
    calls = []
    scheduler = UiDelayedScheduler(lambda: page)

    scheduler(0.0, lambda: calls.append("run"))
    handler = page.handlers.pop()
    asyncio.run(handler())
    asyncio.run(handler())

    assert calls == ["run"]


def test_ui_delayed_scheduler_cancel_blocks_callback_even_if_task_drains() -> None:
    page = _Page()
    calls = []
    scheduler = UiDelayedScheduler(lambda: page)

    handle = scheduler(0.0, lambda: calls.append("run"))
    assert handle is not None
    handle.cancel()
    asyncio.run(page.handlers.pop()())

    assert calls == []


def test_ui_delayed_scheduler_returns_none_without_live_page() -> None:
    scheduler = UiDelayedScheduler(lambda: None)

    assert scheduler(0.0, lambda: None) is None

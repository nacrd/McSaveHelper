from typing import Any

from core.logging.handlers import LogHandler
from core.logging.manager import LogManager


class _CollectingHandler(LogHandler):
    def __init__(self) -> None:
        self.messages = []
        self.closed = False

    def handle(self, record: Any) -> None:
        self.messages.append(record.message)

    def close(self) -> None:
        self.closed = True


def test_shutdown_drains_records_before_closing_handlers() -> None:
    LogManager._instance = None
    manager = LogManager()
    handler = _CollectingHandler()
    manager.add_handler(handler)
    for index in range(100):
        manager.info(f"record-{index}")

    manager.shutdown()

    assert handler.messages == [f"record-{index}" for index in range(100)]
    assert handler.closed is True
    LogManager._instance = None

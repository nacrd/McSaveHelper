import os
from datetime import datetime
from pathlib import Path

import pytest

from app.services.server_properties_service import ServerPropertiesService
from core.logging.handlers import FileHandler
from core.logging.models import LogLevel, LogRecord
from core.utils import safe_destination_world


def _record(message: str) -> LogRecord:
    return LogRecord(
        timestamp=datetime.now(),
        level=LogLevel.INFO,
        message=message,
        module="test",
        thread_id=1,
        thread_name="test",
        extra={},
    )


def test_file_log_rotation_keeps_running_past_backup_limit(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    handler = FileHandler(path, max_size=1, backup_count=2)
    for index in range(6):
        handler.handle(_record(f"record-{index}"))

    assert handler._file is not None and not handler._file.closed
    assert path.is_file()
    assert path.with_suffix(".1.log").is_file()
    assert path.with_suffix(".2.log").is_file()
    handler.close()


def test_server_properties_failed_publish_preserves_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = ServerPropertiesService()
    path = tmp_path / "server.properties"
    props = service.load(path)
    service.save(path, props)
    original = path.read_bytes()

    monkeypatch.setattr(
        "core.io_atomic.os.replace",
        lambda _source, _target: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        service.save(path, props)

    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".server.properties.*.tmp"))


def test_destination_world_rejects_existing_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"
    destination.mkdir()
    other = destination / "other"
    other.mkdir()
    link = destination / "world"
    try:
        os.symlink(other, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(ValueError, match="符号链接"):
        safe_destination_world(source, destination, "world")

"""Lazy region metadata loading tests."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from app.services.region_map import meta as region_map_meta
from app.services.region_map import scan as region_map_scan
from app.services.region_map_service import RegionMapService


def test_silent_scan_registers_paths_without_parsing_metadata(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    region = tmp_path / "r.2.-1.mca"
    region.write_bytes(b"placeholder")
    calls: list[Path] = []

    monkeypatch.setattr(
        region_map_scan,
        "scan_region_dir",
        lambda _path: [region],
    )
    monkeypatch.setattr(
        region_map_meta,
        "scan_region_meta",
        lambda path: calls.append(Path(path)) or {"chunk_count": 1},
    )

    service = RegionMapService()
    try:
        asyncio.run(service.start_silent_scan(str(tmp_path)))

        assert calls == []
        assert service.get_all_data() == {(2, -1): len(b"placeholder")}
        assert service.get_region_meta((2, -1)) == {}
    finally:
        service.close()


def test_region_metadata_is_loaded_once_and_cached(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"placeholder")
    calls: list[Path] = []

    monkeypatch.setattr(
        region_map_scan,
        "scan_region_dir",
        lambda _path: [region],
    )
    monkeypatch.setattr(
        region_map_meta,
        "scan_region_meta",
        lambda path: calls.append(Path(path)) or {"dominant_biome": "plains"},
    )

    service = RegionMapService()
    try:
        asyncio.run(service.start_silent_scan(str(tmp_path)))
        first = asyncio.run(service.ensure_region_meta((0, 0)))
        second = asyncio.run(service.ensure_region_meta((0, 0)))

        assert first == {"dominant_biome": "plains"}
        assert second == first
        assert calls == [region]
        first["dominant_biome"] = "changed"
        assert service.get_region_meta((0, 0))["dominant_biome"] == "plains"
    finally:
        service.close()


def test_late_metadata_result_is_discarded_after_clear(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"placeholder")
    started = threading.Event()
    release = threading.Event()

    def slow_meta(_path: Path) -> dict[str, str]:
        started.set()
        release.wait(timeout=2)
        return {"late": "value"}

    # Let the worker finish only after the scan generation has been invalidated.
    monkeypatch.setattr(region_map_scan, "scan_region_dir", lambda _path: [region])
    monkeypatch.setattr(region_map_meta, "scan_region_meta", slow_meta)

    service = RegionMapService()
    try:
        asyncio.run(service.start_silent_scan(str(tmp_path)))

        async def run_and_clear() -> dict[str, Any]:
            task = asyncio.create_task(service.ensure_region_meta((0, 0)))
            await asyncio.to_thread(started.wait, 1)
            service.clear_data()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            return {}

        assert asyncio.run(run_and_clear()) == {}
        assert service.get_all_region_meta() == {}
    finally:
        service.close()


def test_cancelling_one_metadata_waiter_keeps_shared_parse_alive(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(b"placeholder")
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_meta(_path: Path) -> dict[str, int]:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return {"chunk_count": 7}

    monkeypatch.setattr(region_map_scan, "scan_region_dir", lambda _path: [region])
    monkeypatch.setattr(region_map_meta, "scan_region_meta", slow_meta)
    service = RegionMapService()
    try:
        asyncio.run(service.start_silent_scan(str(tmp_path)))

        async def run_waiters() -> dict[str, int]:
            first = asyncio.create_task(service.ensure_region_meta((0, 0)))
            await asyncio.to_thread(started.wait, 1)
            second = asyncio.create_task(service.ensure_region_meta((0, 0)))
            await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            release.set()
            return await second

        assert asyncio.run(run_waiters()) == {"chunk_count": 7}
        assert calls == 1
    finally:
        release.set()
        service.close()

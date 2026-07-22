"""WorldRepository 读模型契约测试。"""
from __future__ import annotations

from pathlib import Path

from app.services.world_index_service import WorldIndexRegistry, WorldIndexRegistryClosedError
from app.services.world_repository import WorldRepository, WorldSessionPorts
from core.nbt import Compound, File, Int
from core.omni.world_session import WorldSession


def _world(tmp_path: Path, name: str = "world") -> Path:
    world = tmp_path / name
    (world / "region").mkdir(parents=True)
    (world / "playerdata").mkdir()
    (world / "data").mkdir()
    File({"Data": Compound({"DataVersion": Int(1)})}).save(world / "level.dat")
    (world / "region" / "r.0.0.mca").write_bytes(b"region")
    (world / "playerdata" / "aabb.dat").write_bytes(b"player")
    return world


def test_repository_reuses_index_cache(tmp_path: Path) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()
    repository = WorldRepository(registry)
    first = repository.get_index(world)
    second = repository.get_index(world)
    assert second is first
    assert repository.stats().hits >= 1
    registry.close()


def test_repository_open_session_uses_index_snapshot(tmp_path: Path, monkeypatch) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()
    repository = WorldRepository(registry)
    repository.get_index(world)
    calls = {"scan": 0}
    from core.omni import world_scanner

    original = world_scanner.WorldScanner.scan_all

    def counting_scan(self):
        calls["scan"] += 1
        return original(self)

    monkeypatch.setattr(world_scanner.WorldScanner, "scan_all", counting_scan)
    session = repository.open_session(world)
    assert isinstance(session, WorldSession)
    assert calls["scan"] == 0
    assert len(session.get_player_uuids()) == 1
    registry.close()


def test_repository_ports_are_injected(tmp_path: Path) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()
    seen: dict[str, object] = {}

    def lease(path: Path):
        seen["lease"] = path
        from contextlib import nullcontext
        return nullcontext()

    def backup(path: Path) -> Path:
        seen["backup"] = path
        return path / "backup"

    def transaction(path: Path, mutation):
        seen["transaction"] = path
        mutation(path)
        return "ok"

    repository = WorldRepository(
        registry,
        default_ports=WorldSessionPorts(
            write_lease_factory=lease,
            backup_callback=backup,
            transaction_callback=transaction,
        ),
    )
    session = repository.open_session(world)
    assert session._write_lease_factory is lease
    assert session._backup_callback is backup
    assert session._transaction_callback is transaction
    registry.close()


def test_repository_invalidate_and_close(tmp_path: Path) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()
    repository = WorldRepository(registry)
    first = repository.get_index(world)
    repository.invalidate(world)
    second = repository.get_index(world)
    assert second is not first
    repository.close()
    try:
        repository.get_index(world)
        assert False, "expected closed error"
    except WorldIndexRegistryClosedError:
        pass

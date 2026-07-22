"""WorldRepository 读模型契约测试。"""
from __future__ import annotations

from pathlib import Path

from app.bootstrap.services import _default_world_repository
from app.services.backup_service import BackupService
from app.services.world_index_service import WorldIndexRegistry, WorldIndexRegistryClosedError
from app.services.world_repository import WorldRepository, WorldSessionPorts
from app.services.world_transaction import WorldTransactionService
from app.services.world_write_coordinator import WorldWriteCoordinator
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


def test_session_spawn_reuses_current_repository_snapshot(tmp_path: Path) -> None:
    world = _world(tmp_path)
    registry = WorldIndexRegistry()
    repository = WorldRepository(registry)
    session = repository.open_session(world)

    spawned = session.spawn()

    assert spawned is not session
    assert registry.stats().builds == 1
    assert registry.stats().hits == 1
    registry.close()


def test_repository_open_session_normalizes_expanded_user_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    world = _world(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    registry = WorldIndexRegistry()
    repository = WorldRepository(registry)

    session = repository.open_session(Path("~/world"))

    assert session.world_path == world.resolve()
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

    def transaction(path: Path, mutation, cancel_check):
        del cancel_check
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


def test_default_repository_commit_refreshes_session_index(tmp_path: Path) -> None:
    world = _world(tmp_path)
    coordinator = WorldWriteCoordinator()
    backup = BackupService(coordinator)
    registry = WorldIndexRegistry()
    transactions = WorldTransactionService(
        coordinator,
        backup,
        registry.invalidate,
    )
    repository = _default_world_repository(
        registry,
        coordinator,
        backup,
        transactions,
    )
    session = repository.open_session(world)
    session.queue_delete_region(0, 0, Path("region/r.0.0.mca"))

    assert session.commit() is True
    refreshed = session.spawn()

    assert refreshed is not session
    assert refreshed.get_region(0, 0) is None
    assert refreshed._transaction_callback is not None
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

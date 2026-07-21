import threading
from pathlib import Path

from core.nbt import Compound, File, Int
import pytest

from app.services.world_write_coordinator import WorldWriteCoordinator
from core.omni.world_session import WorldSession
from core.world_index import WorldIndexBuilder


def _world(tmp_path: Path) -> Path:
    world = tmp_path / "world"
    world.mkdir()
    File(Compound({"Data": Compound({"Version": Compound({"Id": Int(1)})})})).save(
        world / "level.dat"
    )
    return world


def test_failed_later_action_does_not_publish_earlier_action(tmp_path: Path) -> None:
    world = _world(tmp_path)
    session = WorldSession(world)
    session.queue_custom(lambda target: (target / "marker.txt").write_text("new"))

    def fail(target: Path) -> None:
        del target
        raise RuntimeError("second action failed")

    session.queue_custom(fail)

    assert session.commit(backup=False) is False
    assert not (world / "marker.txt").exists()
    assert session.get_queue_size() == 2
    assert not list(tmp_path.glob(".mcsavehelper_commit_*"))


def test_session_accepts_matching_shared_world_index(tmp_path: Path) -> None:
    world = _world(tmp_path)
    snapshot = WorldIndexBuilder().build(world)

    session = WorldSession(world, index_snapshot=snapshot)

    assert session.get_player_uuids() == []
    assert session.get_dimensions() == []


def test_session_rejects_index_from_another_world(tmp_path: Path) -> None:
    world = _world(tmp_path)
    other_root = tmp_path / "other-root"
    other_root.mkdir()
    other = _world(other_root)
    snapshot = WorldIndexBuilder().build(other)

    with pytest.raises(ValueError, match="索引路径不匹配"):
        WorldSession(world, index_snapshot=snapshot)


def test_session_uses_injected_world_transaction_for_commit(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path)
    calls: list[Path] = []

    def transact(target: Path, mutation) -> None:
        calls.append(target)
        mutation(target)

    session = WorldSession(world, transaction_callback=transact)
    session.queue_custom(
        lambda target: (target / "marker.txt").write_text(
            "committed",
            encoding="utf-8",
        )
    )

    assert session.commit() is True
    assert calls == [world.resolve()]
    assert (world / "marker.txt").read_text(encoding="utf-8") == "committed"
    assert session.get_queue_size() == 0


def test_publish_failure_keeps_original_world(
    tmp_path: Path,
    monkeypatch,
) -> None:
    world = _world(tmp_path)
    session = WorldSession(world)
    session.queue_custom(lambda target: (target / "marker.txt").write_text("new"))
    monkeypatch.setattr(
        "core.omni.action_executor.publish_directory_tree",
        lambda prepared, destination: (_ for _ in ()).throw(
            OSError("publish failed")
        ),
    )

    assert session.commit(backup=False) is False
    assert not (world / "marker.txt").exists()


def test_managed_backup_callback_replaces_legacy_backup(tmp_path: Path) -> None:
    world = _world(tmp_path)
    calls = []

    def backup(target: Path) -> Path:
        calls.append(target)
        return tmp_path / "managed-backup"

    session = WorldSession(world, backup_callback=backup)
    session.queue_custom(lambda target: (target / "marker.txt").write_text("ok"))

    assert session.commit(backup=True) is True
    assert calls == [world.resolve()]
    assert not (tmp_path / "world.backup").exists()
    assert (world / "marker.txt").read_text() == "ok"


def test_world_write_lease_rejects_concurrent_commit(tmp_path: Path) -> None:
    world = _world(tmp_path)
    coordinator = WorldWriteCoordinator()
    session = WorldSession(
        world,
        write_lease_factory=coordinator.reserve,
    )
    session.queue_custom(lambda target: (target / "marker.txt").write_text("ok"))
    results = []

    with coordinator.reserve(world):
        thread = threading.Thread(
            target=lambda: results.append(session.commit(backup=False))
        )
        thread.start()
        thread.join()

    assert results == [False]
    assert not (world / "marker.txt").exists()
    assert session.get_queue_size() == 1


def test_region_delete_targets_only_selected_dimension(tmp_path: Path) -> None:
    world = _world(tmp_path)
    overworld = world / "region" / "r.0.0.mca"
    nether = world / "DIM-1" / "region" / "r.0.0.mca"
    for path in (overworld, nether):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"region")
    session = WorldSession(world)
    session.queue_delete_region(0, 0, Path("DIM-1/region/r.0.0.mca"))

    assert session.commit(backup=False) is True
    assert overworld.exists()
    assert not nether.exists()


def test_chunk_target_outside_world_is_rejected_before_write(tmp_path: Path) -> None:
    world = _world(tmp_path)
    outside = tmp_path / "outside.mca"
    outside.write_bytes(b"outside")
    session = WorldSession(world)
    with pytest.raises(ValueError, match="越过存档边界"):
        session.queue_modify_chunk(Path("../outside.mca"), 0, 0, object())

    assert outside.read_bytes() == b"outside"

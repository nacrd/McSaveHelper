from pathlib import Path
from typing import Dict

from app.core.save_context_manager import SaveContextManager
from app.models.save_context import CurrentSaveContext
from app.models.save_store import CurrentSaveStore, RecentSave


class FakeConfig:
    def __init__(self, recent_saves=None) -> None:
        self._config: Dict[str, object] = {
            "recent_saves": list(recent_saves or [])
        }
        self.save_count = 0

    @property
    def config(self) -> Dict[str, object]:
        return self._config

    def save(self) -> None:
        self.save_count += 1


def test_store_publishes_selected_context_and_clear() -> None:
    store = CurrentSaveStore()
    published = []
    store.subscribe_current(published.append)
    context = CurrentSaveContext.from_path(Path("world"))

    store.select(context)
    store.clear()

    assert published == [context, None]
    assert store.current is None
    assert store.current_path is None


def test_store_normalizes_recent_saves_and_publishes_snapshot() -> None:
    store = CurrentSaveStore()
    published = []
    store.subscribe_recent(published.append)
    store.replace_recent(
        [
            {"path": "a", "name": "A"},
            {"path": "a", "name": "duplicate"},
            {"path": "b"},
            {"path": "c", "name": "C"},
            {"path": "d", "name": "D"},
            {"path": "e", "name": "E"},
            {"path": "f", "name": "ignored"},
            {"name": "missing path"},
        ]
    )

    assert store.recent == (
        RecentSave("a", "A"),
        RecentSave("b", ""),
        RecentSave("c", "C"),
        RecentSave("d", "D"),
        RecentSave("e", "E"),
    )
    assert published == [store.recent]


def test_manager_selects_valid_save_and_persists_recent(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").touch()
    config = FakeConfig()
    store = CurrentSaveStore()
    activated = []
    warnings = []
    errors = []
    manager = SaveContextManager(
        config=config,
        store=store,
        pick_directory=lambda: str(world),
        warn_dialog=lambda title, message: warnings.append((title, message)),
        error_dialog=lambda title, message: errors.append((title, message)),
        activate_save=activated.append,
    )

    manager.initialize()
    manager.on_import_save()

    assert store.current_path == str(world)
    assert activated == [str(world)]
    assert manager.get_recent_saves() == [
        {"path": str(world), "name": "world"}
    ]
    assert config.config["recent_saves"] == manager.get_recent_saves()
    assert config.save_count == 1
    assert warnings == []
    assert errors == []


def test_manager_removes_invalid_recent_save(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing")
    config = FakeConfig([{"path": missing, "name": "missing"}])
    store = CurrentSaveStore()
    warnings = []
    manager = SaveContextManager(
        config=config,
        store=store,
        pick_directory=lambda: None,
        warn_dialog=lambda title, message: warnings.append((title, message)),
        error_dialog=lambda title, message: None,
        activate_save=lambda path: None,
    )

    manager.initialize()
    manager.on_recent_save_select(missing)

    assert manager.get_recent_saves() == []
    assert config.config["recent_saves"] == []
    assert config.save_count == 1
    assert warnings and warnings[0][0] == "提示"

"""Tests for auto-import Minecraft language on save selection."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.models.config import ApplicationSettings
from app.models.save_context import CurrentSaveContext
from app.services.config_service import ConfigService
from app.services.item.language_loader import normalize_locale


def test_auto_import_mc_lang_default_enabled(tmp_path: Path) -> None:
    config = ConfigService(tmp_path)
    assert config.is_auto_import_mc_lang_enabled() is True
    assert config.get_settings().auto_import_mc_lang is True


def test_auto_import_mc_lang_can_disable(tmp_path: Path) -> None:
    config = ConfigService(tmp_path)
    settings = ApplicationSettings(auto_import_mc_lang=False)
    config.update_settings(settings)
    assert config.is_auto_import_mc_lang_enabled() is False


def test_normalize_locale_from_ui_language() -> None:
    assert normalize_locale("zh_CN") == "zh_cn"
    assert normalize_locale("en_US") == "en_us"


def _make_app_stub(
    *,
    enabled: bool = True,
    minecraft_dir: str = "",
    item: Any | None = None,
) -> Any:
    """Build a minimal Application shell for auto-import unit tests."""
    import threading

    from app.application import Application

    app = Application.__new__(Application)
    app._auto_lang_import_path = None
    app._auto_lang_import_generation = 0
    app._auto_lang_import_lock = threading.Lock()
    app.page = SimpleNamespace()  # run_on_ui tolerates missing run_task
    # config/item/i18n 是只读 property，经 services 注入测试替身。
    app.services = SimpleNamespace(
        config=SimpleNamespace(
            is_auto_import_mc_lang_enabled=lambda: enabled,
            get_minecraft_dir=lambda: minecraft_dir,
        ),
        item=item
        or SimpleNamespace(
            normalize_locale=normalize_locale,
            import_language_from_local_minecraft=(
                lambda **kwargs: SimpleNamespace(
                    count=0,
                    locale=kwargs.get("locale", ""),
                    sources=(),
                )
            ),
        ),
        i18n=SimpleNamespace(current_language="zh_CN"),
    )
    app.gui_optimizer = SimpleNamespace(notification_manager=None)
    logs: list[tuple[str, str]] = []
    app.log = lambda msg, level="INFO": logs.append((level, msg))
    app._t = (
        lambda key, default="", **kw: default.format(**kw) if kw else default
    )
    app._logs = logs
    return app


def test_auto_import_worker_uses_save_and_config(tmp_path: Path) -> None:
    """Exercise Application worker wiring without Flet UI."""
    mc = tmp_path / ".minecraft"
    (mc / "assets" / "indexes").mkdir(parents=True)
    (mc / "assets" / "objects").mkdir(parents=True)
    save = mc / "versions" / "26.2-NeoForge" / "saves" / "World"
    save.mkdir(parents=True)

    captured: dict[str, Any] = {}

    class FakeItem:
        def normalize_locale(self, locale: str) -> str:
            return normalize_locale(locale)

        def import_language_from_local_minecraft(self, locale: str, **kwargs):
            captured["locale"] = locale
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                count=12,
                locale=locale,
                sources=("assets/objects/ab/hash",),
                jar_path=str(mc / "assets" / "indexes" / "32.json"),
            )

    app = _make_app_stub(minecraft_dir=str(mc), item=FakeItem())
    app._auto_lang_import_path = str(save)
    app._auto_lang_import_generation = 1

    app._auto_import_mc_language_worker(str(save), generation=1)

    assert captured["locale"] == "zh_cn"
    assert captured["kwargs"]["configured_dir"] == Path(str(mc))
    assert captured["kwargs"]["start_path"] == Path(str(save))
    assert any("已自动导入" in msg or "12" in msg for _, msg in app._logs)


def test_schedule_skips_when_disabled(tmp_path: Path) -> None:
    app = _make_app_stub(enabled=False)
    context = CurrentSaveContext.from_path(tmp_path / "World")
    app._schedule_auto_import_mc_language(context)
    assert app._auto_lang_import_path is None
    assert app._auto_lang_import_generation == 0


def test_schedule_deduplicates_same_path(tmp_path: Path, monkeypatch) -> None:
    started: list[str] = []

    class FakeThread:
        def __init__(self, target=None, args=(), name="", daemon=False):
            self._target = target
            self._args = args

        def start(self) -> None:
            started.append(self._args[0])

    monkeypatch.setattr("app.application.threading.Thread", FakeThread)

    app = _make_app_stub(enabled=True)
    context = CurrentSaveContext.from_path(tmp_path / "World")
    app._schedule_auto_import_mc_language(context)
    app._schedule_auto_import_mc_language(context)

    assert started == [str(context.path)]
    assert app._auto_lang_import_generation == 1


def test_worker_discards_stale_generation(tmp_path: Path) -> None:
    calls: list[str] = []

    class FakeItem:
        def normalize_locale(self, locale: str) -> str:
            return normalize_locale(locale)

        def import_language_from_local_minecraft(self, locale: str, **kwargs):
            del kwargs
            return SimpleNamespace(
                count=5,
                locale=locale,
                sources=("source",),
            )

    app = _make_app_stub(item=FakeItem())
    save = str(tmp_path / "World")
    app._auto_lang_import_path = save
    app._auto_lang_import_generation = 2  # newer selection already scheduled

    # Stale worker still completes import I/O, but must not log success.
    original_log = app.log

    def tracking_log(msg: str, level: str = "INFO") -> None:
        calls.append(msg)
        original_log(msg, level)

    app.log = tracking_log
    app._auto_import_mc_language_worker(save, generation=1)

    assert not any("已自动导入" in msg for msg in calls)


def test_worker_clears_path_on_failure_for_retry(tmp_path: Path) -> None:
    class BrokenItem:
        def normalize_locale(self, locale: str) -> str:
            return normalize_locale(locale)

        def import_language_from_local_minecraft(self, **kwargs):
            del kwargs
            raise OSError("missing assets")

    app = _make_app_stub(item=BrokenItem())
    save = str(tmp_path / "World")
    app._auto_lang_import_path = save
    app._auto_lang_import_generation = 1

    app._auto_import_mc_language_worker(save, generation=1)

    assert app._auto_lang_import_path is None
    assert any("失败" in msg for _, msg in app._logs)

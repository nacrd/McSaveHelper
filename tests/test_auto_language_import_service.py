"""自动语言导入服务的代次与生命周期测试。"""
from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import cast

from app.models.save_context import CurrentSaveContext
from app.services.auto_language_import_service import AutoLanguageImportService
from app.services.config_service import ConfigService
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.i18n_service import I18nService
from app.services.item.language_loader import LanguageImportResult
from app.services.item_service import ItemService


class _Config:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def is_auto_import_mc_lang_enabled(self) -> bool:
        return self.enabled

    @staticmethod
    def get_minecraft_dir() -> str:
        return ""


class _I18n:
    current_language = "zh_CN"


class _Item:
    def __init__(self, gate: Event | None = None) -> None:
        self.calls: list[Path] = []
        self.gate = gate

    @staticmethod
    def normalize_locale(locale: str) -> str:
        return locale.lower()

    def import_language_from_local_minecraft(
        self,
        locale: str,
        *,
        configured_dir: Path | None,
        start_path: Path,
    ) -> LanguageImportResult:
        del configured_dir
        self.calls.append(start_path)
        if self.gate is not None:
            assert self.gate.wait(2.0)
        return LanguageImportResult(
            count=3,
            locale=locale,
            sources=("assets",),
        )


def _service(
    runtime: ExecutionRuntime,
    item: _Item,
    *,
    enabled: bool = True,
) -> AutoLanguageImportService:
    return AutoLanguageImportService(
        cast(ConfigService, _Config(enabled)),
        cast(I18nService, _I18n()),
        cast(ItemService, item),
        runtime,
    )


def test_schedule_imports_once_and_delivers_current_result(tmp_path: Path) -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(1, 4),
        cpu_limits=LaneLimits(1, 1),
    )
    item = _Item()
    service = _service(runtime, item)
    delivered = Event()
    context = CurrentSaveContext.from_path(tmp_path / "world")

    assert service.schedule(context, lambda _result: delivered.set()) is True
    assert service.schedule(context, lambda _result: delivered.set()) is False
    assert delivered.wait(2.0)

    service.close()
    assert runtime.shutdown(wait=True, timeout=2.0)
    assert item.calls == [context.path.resolve()]


def test_new_world_drops_previous_generation_callback(tmp_path: Path) -> None:
    runtime = ExecutionRuntime(
        io_limits=LaneLimits(2, 4),
        cpu_limits=LaneLimits(1, 1),
    )
    gate = Event()
    item = _Item(gate)
    service = _service(runtime, item)
    delivered: list[str] = []
    second_delivered = Event()
    first = CurrentSaveContext.from_path(tmp_path / "first")
    second = CurrentSaveContext.from_path(tmp_path / "second")

    assert service.schedule(first, lambda _result: delivered.append("first"))

    def record_second(_result: LanguageImportResult) -> None:
        delivered.append("second")
        second_delivered.set()

    assert service.schedule(second, record_second)
    gate.set()
    assert second_delivered.wait(2.0)
    runtime.shutdown(wait=True, timeout=2.0)

    service.close()
    assert delivered == ["second"]


def test_disabled_service_does_not_submit(tmp_path: Path) -> None:
    runtime = ExecutionRuntime()
    item = _Item()
    service = _service(runtime, item, enabled=False)

    assert service.schedule(CurrentSaveContext.from_path(tmp_path)) is False

    service.close()
    assert runtime.shutdown(wait=True, timeout=2.0)
    assert item.calls == []

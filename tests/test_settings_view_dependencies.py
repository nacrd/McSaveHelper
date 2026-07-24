"""设置快照与设置页端口的回归测试。"""
import threading
from pathlib import Path

import flet as ft

from app.models.config import ApplicationSettings
from app.models.responsive_layout import resolve_responsive_layout
from app.services.config_service import ConfigService
from app.services.cache_registry import CacheRegistry
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.operation_metrics import UiDeliveryMetricsSummary
from app.ui.views.settings import SettingsView, SettingsViewDependencies


def _translate(key: str, default: str = "", **kwargs) -> str:
    del key, kwargs
    return default


def _dependencies(
    saved: list[ApplicationSettings],
    runtime: ExecutionRuntime,
    saved_event: threading.Event | None = None,
) -> SettingsViewDependencies:
    defaults = ApplicationSettings()

    def save(settings: ApplicationSettings) -> None:
        saved.append(settings)
        if saved_event is not None:
            saved_event.set()

    return SettingsViewDependencies(
        load_settings=lambda: defaults,
        save_settings=save,
        reset_settings=lambda: defaults,
        translate=_translate,
        apply_theme=lambda theme: None,
        apply_language=lambda language: None,
        set_sidebar_mode=lambda mode: None,
        set_log_panel_visible=lambda visible: None,
        configure_performance_monitor=lambda enabled, interval: None,
        set_performance_interval=lambda interval: None,
        info_dialog=lambda title, message: None,
        error_dialog=lambda title, message: None,
        pick_directory=lambda: None,
        cache_snapshot=CacheRegistry().stats,
        clear_caches=lambda: {
            "deleted_files": 0,
            "freed_bytes": 0,
            "memory_chunks_cleared": 0,
        },
        cache_path=lambda: "",
        execution_runtime=runtime,
        runtime_snapshot=runtime.snapshot,
        ui_delivery_summary=UiDeliveryMetricsSummary,
        save_debounce_seconds=0,
    )


def test_settings_view_collects_validated_snapshot() -> None:
    saved: list[ApplicationSettings] = []
    saved_event = threading.Event()
    limits = LaneLimits(max_workers=1, queue_capacity=2)
    runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
    view = SettingsView(_dependencies(saved, runtime, saved_event))
    applied_event = threading.Event()
    apply_success = view._apply_save_success

    def apply_and_signal() -> None:
        apply_success()
        applied_event.set()

    view._apply_save_success = apply_and_signal
    try:
        view._api_timeout_field.value = "999"
        view._perf_print_interval_field.value = "1"
        view._max_concurrent_field.value = "99"
        view._cleanup_field.value = " *.log \n\n cache/ "

        view._persist()

        assert saved_event.wait(2)
        assert applied_event.wait(2)
        assert saved == [ApplicationSettings(
            api_timeout=60,
            performance_print_interval=5,
            max_concurrent=16,
            cleanup_patterns=("*.log", "cache/"),
        )]
        assert view._save_status_text.value == "已保存"
    finally:
        view.dispose()
        runtime.shutdown(wait=True)


def test_settings_layout_stacks_in_compact_mode() -> None:
    runtime = ExecutionRuntime()
    view = SettingsView(_dependencies([], runtime))

    view.set_compact_mode(True)
    assert isinstance(view._settings_host.content, ft.Column)
    assert view._settings_host.content.controls == view._sections

    view.set_compact_mode(False)
    assert isinstance(view._settings_host.content, ft.Row)
    view.dispose()
    runtime.shutdown(wait=True)


def test_settings_layout_uses_one_column_until_roomy_width() -> None:
    runtime = ExecutionRuntime()
    view = SettingsView(_dependencies([], runtime))

    view.set_responsive_layout(resolve_responsive_layout(1100, 820))
    assert isinstance(view._settings_host.content, ft.Column)

    view.set_responsive_layout(resolve_responsive_layout(1400, 820))
    assert isinstance(view._settings_host.content, ft.Row)
    view.dispose()
    runtime.shutdown(wait=True)


def test_config_service_persists_typed_settings(tmp_path: Path) -> None:
    config = ConfigService(tmp_path)
    settings = ApplicationSettings(
        version_detection=False,
        api_timeout=25,
        theme="light",
        language="en_US",
        sidebar_mode="collapsed",
        auto_clear_log=False,
        show_log_panel=False,
        enable_performance_monitor=True,
        performance_print_interval=15,
        max_concurrent=8,
        preserve_structure=False,
        cleanup_patterns=("session.lock",),
        minecraft_dir=r"F:\Game\minecraft\.minecraft",
        auto_import_mc_lang=False,
    )

    config.update_settings(settings)
    stored = config.get_config_dict()

    assert config.get_settings() == settings
    assert stored["minecraft_dir"] == r"F:\Game\minecraft\.minecraft"
    assert config.get_minecraft_dir() == r"F:\Game\minecraft\.minecraft"
    assert stored["auto_import_mc_lang"] is False
    assert config.is_auto_import_mc_lang_enabled() is False
    assert stored["batch_processing"] == {
        "max_concurrent": 8,
        "preserve_structure": False,
    }
    assert "preserve_structure" not in stored["ui_settings"]
    assert config.migration.version_detection is False
    assert (tmp_path / ConfigService.CONFIG_FILENAME).exists()

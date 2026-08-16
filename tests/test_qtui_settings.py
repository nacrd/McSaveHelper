"""Qt 设置视图测试：构建、收集、持久化、重置与生命周期。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
from PySide6.QtWidgets import QApplication, QBoxLayout

from app.adapters.file_dialogs import FileType
from app.models.config import ApplicationSettings
from app.qtui.views.settings import SettingsView, SettingsViewDependencies
from app.services.cache_registry import CacheRegistry
from app.services.config_service import ConfigService
from app.services.execution_runtime import (
    ExecutionRuntime,
    ExecutionRuntimeSnapshot,
    LaneLimits,
)
from app.services.operation_metrics import UiDeliveryMetricsSummary


def _wait_until(
    predicate: Callable[[], bool],
    timeout_s: float = 5.0,
) -> bool:
    """轮询等待条件成立（避免固定长 sleep 协调）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeHost:
    """设置页依赖端口的最小测试宿主。"""

    def __init__(self, config_dir: Path) -> None:
        limits = LaneLimits(max_workers=2, queue_capacity=8)
        self.runtime = ExecutionRuntime(io_limits=limits, cpu_limits=limits)
        self.config = ConfigService(config_dir)
        self.cache_registry = CacheRegistry(budget_bytes=1024 * 1024)
        self.infos: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.themes: list[str] = []
        self.languages: list[str] = []
        self.sidebar_modes: list[str] = []
        self.log_panel_visible: list[bool] = []
        self.perf_monitor: list[tuple[bool, float]] = []
        self.perf_intervals: list[float] = []

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        del kwargs
        return default

    def apply_theme(self, theme: str) -> None:
        self.themes.append(theme)

    def apply_language(self, language: str) -> None:
        self.languages.append(language)

    def set_sidebar_mode(self, mode: str) -> None:
        self.sidebar_modes.append(mode)

    def set_log_panel_visible(self, visible: bool) -> None:
        self.log_panel_visible.append(visible)

    def configure_performance_monitor(self, enabled: bool, interval: float) -> None:
        self.perf_monitor.append((enabled, interval))

    def set_performance_interval(self, seconds: float) -> None:
        self.perf_intervals.append(seconds)

    def info_dialog(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def error_dialog(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def pick_directory(self) -> Optional[str]:
        return None

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        del title, default_ext, file_types
        return None

    def clear_caches(self) -> dict[str, int]:
        return {
            "deleted_files": 3,
            "freed_bytes": 4096,
            "memory_chunks_cleared": 2,
        }

    @staticmethod
    def cache_path() -> str:
        return "C:/tmp/map-cache"

    @staticmethod
    def runtime_snapshot() -> Optional[ExecutionRuntimeSnapshot]:
        return None

    @staticmethod
    def ui_delivery_summary() -> UiDeliveryMetricsSummary:
        return UiDeliveryMetricsSummary()

    def make_dependencies(self) -> SettingsViewDependencies:
        return SettingsViewDependencies(
            load_settings=self.config.get_settings,
            save_settings=self.config.update_settings,
            reset_settings=self._reset_settings,
            translate=self.translate,
            apply_theme=self.apply_theme,
            apply_language=self.apply_language,
            set_sidebar_mode=self.set_sidebar_mode,
            set_log_panel_visible=self.set_log_panel_visible,
            configure_performance_monitor=self.configure_performance_monitor,
            set_performance_interval=self.set_performance_interval,
            info_dialog=self.info_dialog,
            error_dialog=self.error_dialog,
            pick_directory=self.pick_directory,
            save_file=self.save_file,
            cache_snapshot=self.cache_registry.stats,
            clear_caches=self.clear_caches,
            cache_path=self.cache_path,
            execution_runtime=self.runtime,
            runtime_snapshot=self.runtime_snapshot,
            ui_delivery_summary=self.ui_delivery_summary,
            save_debounce_seconds=0.05,
        )

    def _reset_settings(self) -> ApplicationSettings:
        self.config.reset_config()
        return self.config.get_settings()

    def close(self) -> None:
        self.runtime.shutdown(wait=True, timeout=5.0)


@pytest.fixture
def host(qt_app: object, tmp_path: Path) -> Iterator[FakeHost]:
    del qt_app
    fake = FakeHost(tmp_path / "config")
    yield fake
    fake.close()


@pytest.fixture
def view(host: FakeHost) -> Iterator[SettingsView]:
    yield SettingsView(host.make_dependencies())


def test_view_builds_sections(view: SettingsView) -> None:
    assert len(view._sections) == 6
    assert "更改会自动保存" in view._save_status_label.text()
    # 默认值投影
    assert view._theme_dropdown.property("value_key") == "dark"


def test_settings_columns_stack_in_narrow_window(view: SettingsView) -> None:
    view.resize(900, 700)
    view.show()
    QApplication.processEvents()

    assert view._columns_layout is not None
    assert view._columns_layout.direction() == QBoxLayout.Direction.TopToBottom

    view.resize(1280, 800)
    QApplication.processEvents()

    assert view._columns_layout.direction() == QBoxLayout.Direction.LeftToRight


def test_collect_settings_reads_controls(view: SettingsView, host: FakeHost) -> None:
    view._version_var.setChecked(False)
    view._api_timeout_field.setText("15")
    view._minecraft_dir_field.setText("F:/minecraft")
    view._cleanup_field.setPlainText("*.log\ncache/\n")
    view._max_concurrent_field.setText("4")

    settings = view._collect_settings()

    assert settings.version_detection is False
    assert settings.api_timeout == 15
    assert settings.minecraft_dir == "F:/minecraft"
    assert settings.cleanup_patterns == ("*.log", "cache/")
    assert settings.max_concurrent == 4


def test_persist_saves_to_config(
    view: SettingsView,
    host: FakeHost,
) -> None:
    view._api_timeout_field.setText("22")
    view._on_api_timeout_change()

    assert _wait_until(lambda: host.config.get_settings().api_timeout == 22)


def test_theme_change_applies_and_persists(
    view: SettingsView,
    host: FakeHost,
) -> None:
    view._theme_dropdown.setCurrentIndex(1)  # 浅色

    assert _wait_until(lambda: host.config.get_settings().theme == "light")
    assert host.themes == ["light"]


def test_language_change_applies(view: SettingsView, host: FakeHost) -> None:
    view._lang_dropdown.setCurrentIndex(1)  # English

    assert _wait_until(lambda: host.config.get_settings().language == "en_US")
    assert host.languages == ["en_US"]


def test_browse_minecraft_dir_persists(
    host: FakeHost,
    tmp_path: Path,
) -> None:
    host.pick_directory = lambda: str(tmp_path)  # type: ignore[method-assign]
    view = SettingsView(host.make_dependencies())

    view._browse_minecraft_dir()

    assert view._minecraft_dir_field.text() == str(tmp_path)
    assert _wait_until(
        lambda: host.config.get_settings().minecraft_dir == str(tmp_path)
    )


def test_restore_default_cleanup(view: SettingsView, host: FakeHost) -> None:
    view._cleanup_field.setPlainText("custom/")

    view._restore_default_cleanup()

    assert view._cleanup_field.toPlainText() == "*.log\ncache/\nlogs/"
    assert _wait_until(
        lambda: host.config.get_settings().cleanup_patterns
        == ("*.log", "cache/", "logs/")
    )


def test_cache_clear_reports_success(
    view: SettingsView,
    host: FakeHost,
) -> None:
    view._clear_map_cache()

    assert _wait_until(lambda: bool(host.infos))
    assert "已清理地图缓存" in host.infos[0][1]


def test_reset_restores_defaults(
    view: SettingsView,
    host: FakeHost,
) -> None:
    host.config.update_settings(ApplicationSettings(api_timeout=55))
    assert host.config.get_settings().api_timeout == 55

    view._reset()

    assert _wait_until(lambda: bool(host.infos))
    assert host.config.get_settings().api_timeout == 10
    assert host.infos[0][1] == "已恢复默认设置"


def test_did_mount_refreshes_cache(view: SettingsView, host: FakeHost) -> None:
    view.did_mount()

    assert _wait_until(
        lambda: "应用缓存" in view._cache_summary.text()
        or "无法读取" in view._cache_summary.text()
    )


def test_dispose_is_idempotent(view: SettingsView) -> None:
    view.dispose()
    view.dispose()

    assert view._state.is_disposed is True

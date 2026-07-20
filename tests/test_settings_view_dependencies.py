"""设置快照与设置页端口的回归测试。"""
from pathlib import Path

from app.models.config import ApplicationSettings
from app.services.config_service import ConfigService
from app.ui.views.settings import SettingsView, SettingsViewDependencies


def _translate(key: str, default: str = "", **kwargs) -> str:
    del key, kwargs
    return default


def _dependencies(saved: list[ApplicationSettings]) -> SettingsViewDependencies:
    defaults = ApplicationSettings()
    return SettingsViewDependencies(
        load_settings=lambda: defaults,
        save_settings=saved.append,
        reset_settings=lambda: None,
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
    )


def test_settings_view_collects_validated_snapshot() -> None:
    saved: list[ApplicationSettings] = []
    view = SettingsView(_dependencies(saved))
    view._api_timeout_field.value = "999"
    view._perf_print_interval_field.value = "1"
    view._max_concurrent_field.value = "99"
    view._cleanup_field.value = " *.log \n\n cache/ "

    view._persist()

    assert saved == [ApplicationSettings(
        api_timeout=60,
        performance_print_interval=5,
        max_concurrent=16,
        cleanup_patterns=("*.log", "cache/"),
    )]


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
    )

    config.update_settings(settings)
    stored = config.get_config_dict()

    assert config.get_settings() == settings
    assert stored["minecraft_dir"] == r"F:\Game\minecraft\.minecraft"
    assert config.get_minecraft_dir() == r"F:\Game\minecraft\.minecraft"
    assert stored["batch_processing"] == {
        "max_concurrent": 8,
        "preserve_structure": False,
    }
    assert "preserve_structure" not in stored["ui_settings"]
    assert config.migration.version_detection is False
    assert (tmp_path / ConfigService.CONFIG_FILENAME).exists()

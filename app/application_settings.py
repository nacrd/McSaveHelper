"""Settings coordination helpers for the application composition root."""
from __future__ import annotations

from typing import Any

import flet as ft

from app.ui.theme import THEME, get_theme_manager


class SettingsCoordinationMixin:
    """Settings view wiring and cache helpers."""

    config: Any
    i18n: Any
    page: Any
    services: Any
    gui_optimizer: Any
    window_manager: Any
    floating_log_panel: Any
    _sidebar: Any
    _log_fab: Any
    _t: Any
    info_dialog: Any
    error_dialog: Any
    pick_directory: Any

    def create_settings_view(self) -> ft.Control:
        """Compose the settings view with explicit application ports."""
        from app.ui.views.settings import SettingsView, SettingsViewDependencies

        return SettingsView(SettingsViewDependencies(
            load_settings=self.config.get_settings,
            save_settings=self.config.update_settings,
            reset_settings=self._reset_settings,
            translate=self._t,
            apply_theme=self._apply_theme,
            apply_language=self._apply_language,
            set_sidebar_mode=self._set_sidebar_mode,
            set_log_panel_visible=self._set_log_panel_visible,
            configure_performance_monitor=(
                self.gui_optimizer.configure_performance_monitor
            ),
            set_performance_interval=(
                self.gui_optimizer.set_performance_print_interval
            ),
            info_dialog=self.info_dialog,
            error_dialog=self.error_dialog,
            pick_directory=self.pick_directory,
            cache_snapshot=self.services.cache_registry.stats,
            clear_caches=self._clear_application_caches,
            cache_path=self._map_cache_path,
        ))

    def _clear_application_caches(self) -> dict[str, int]:
        """Clear memory and persistent tile caches."""
        from core.mca.tile_cache import clear_all_caches

        self.services.cache_registry.clear_all()
        result = clear_all_caches()
        return {
            "deleted_files": int(result.get("deleted_files", 0) or 0),
            "freed_bytes": int(result.get("freed_bytes", 0) or 0),
            "memory_chunks_cleared": int(
                result.get("memory_chunks_cleared", 0) or 0
            ),
        }

    @staticmethod
    def _map_cache_path() -> str:
        """Return the persistent map cache path."""
        from core.mca.tile_cache import cache_dir

        return str(cache_dir())

    def _apply_theme(self, theme: str) -> None:
        """Apply persisted theme selection."""
        get_theme_manager().set_mode(theme)
        self.page.bgcolor = THEME.bg_primary
        self.page.window.bgcolor = THEME.bg_primary
        self.page.theme_mode = (
            ft.ThemeMode.LIGHT if theme == "light" else ft.ThemeMode.DARK
        )
        self.page.update()

    def _apply_language(self, language: str) -> None:
        """Apply language selection."""
        self.i18n.set_language(language)

    def _set_sidebar_mode(self, mode: str) -> None:
        """Refresh responsive sidebar after preference change."""
        del mode
        if hasattr(self, "_sidebar"):
            self.window_manager.refresh_responsive_layout()

    def _set_log_panel_visible(
        self,
        visible: bool,
    ) -> None:
        """Apply log-panel visibility."""
        if not hasattr(self, "_log_fab"):
            return
        self._log_fab.set_visible(visible)
        self.floating_log_panel.set_visible(False)

    def _reset_settings(self) -> None:
        """Reset settings and apply all immediate effects."""
        self.config.reset_config()
        settings = self.config.get_settings()
        self._apply_theme(settings.theme)
        self._apply_language(settings.language)
        self._set_sidebar_mode(settings.sidebar_mode)
        self._set_log_panel_visible(settings.show_log_panel)
        self.gui_optimizer.configure_performance_monitor(
            settings.enable_performance_monitor,
            float(settings.performance_print_interval),
        )


__all__ = ["SettingsCoordinationMixin"]

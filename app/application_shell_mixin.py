"""Shell and error handling helpers for the composition root."""
from __future__ import annotations

import time
import traceback
from typing import Any

import flet as ft

from core.logger import LogLevel, logger, setup_default_logging
from app.ui.application_shell import (
    ApplicationShellDependencies,
    build_application_shell,
)
from app.core.view_manager import ViewHost
from app.core.window_manager import ResponsiveShellHost


class ApplicationShellMixin:
    """Build the desktop shell and install logging/error handlers."""

    page: Any
    config: Any
    view_manager: Any
    window_manager: Any
    progress_manager: Any
    save_context_manager: Any
    dialog_manager: Any
    gui_optimizer: Any
    floating_log_panel: Any
    _t: Any
    log: Any

    def _build_ui(self) -> None:
        shell = build_application_shell(ApplicationShellDependencies(
            page=self.page,
            translate=self._t,
            on_tab_select=self.view_manager.switch_view,
            on_tabs_reorder=self._on_tabs_reorder,
            on_import_save=self.save_context_manager.on_import_save,
            on_recent_save_select=(
                self.save_context_manager.on_recent_save_select
            ),
            recent_saves=self.save_context_manager.get_recent_saves(),
            show_log_panel=self.config.ui_settings.get(
                "show_log_panel",
                True,
            ),
            progress_control=self.progress_manager.create_progress_ui(),
            title_bar=self.window_manager.build_title_bar(),
        ))
        self._tab_defs = shell.tab_defs
        self._content = shell.content
        self._sidebar = shell.sidebar
        self._scrollable_content = shell.scrollable_content
        self.floating_log_panel = shell.floating_log_panel
        self._log_fab = shell.log_button
        self._main_row = shell.main_row
        self._shell = shell.shell
        self.view_manager.attach_host(ViewHost(content=shell.content))
        self.window_manager.attach_responsive_host(ResponsiveShellHost(
            sidebar=self._sidebar,
            main_row=self._main_row,
            shell=self._shell,
            scrollable_content=self._scrollable_content,
            content=self._content,
        ))
        self.window_manager.refresh_responsive_layout()
        self.page.add(shell.frame)

    def _on_tabs_reorder(self, tabs: list) -> None:
        self._tab_defs = list(tabs)

    def _init_logging(self) -> None:
        def ui_log_callback(message: str, tag: str) -> None:
            ts = time.strftime("%H:%M:%S")
            self.floating_log_panel.log(
                f"[{ts}] [{tag.upper()}] {message}",
                tag.lower(),
            )

        setup_default_logging(
            enable_console=True,
            enable_file=True,
            file_path=None,
            enable_ui=True,
            ui_callback=ui_log_callback,
            level=LogLevel.INFO,
        )
        logger.info("MCSaveHelper 应用启动", module="App")

    def _on_page_error(self, e: ft.Event[ft.Page]) -> None:
        error_msg = str(e.data) if hasattr(e, "data") else str(e)
        print(f"[PAGE ERROR] {error_msg}")
        traceback.print_exc()
        try:
            self.log(f"未捕获的异常: {error_msg}", "ERROR")
            if (
                hasattr(self, "gui_optimizer")
                and self.gui_optimizer.notification_manager
            ):
                try:
                    from app.ui.feedback import ErrorReportDialog
                    ErrorReportDialog(
                        self.page,
                        error=Exception(error_msg),
                        context="页面错误",
                    ).show()
                    return
                except Exception:
                    pass
            self.dialog_manager.error_dialog(
                self._t("dialogs.error", "错误"),
                f"发生意外错误: {error_msg}",
            )
        except Exception:
            pass


__all__ = ["ApplicationShellMixin"]

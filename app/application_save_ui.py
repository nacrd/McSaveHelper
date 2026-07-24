"""Save selection UI adapters for the composition root."""
from __future__ import annotations

from typing import Any, Optional

from app.models.save_context import CurrentSaveContext
from app.models.save_store import RecentSave


class SaveContextUiMixin:
    """Reflect current/recent save state in shell controls."""

    gui_optimizer: Any
    view_manager: Any
    _sidebar: Any
    _schedule_auto_import_mc_language: Any

    def _on_current_save_changed(
        self,
        context: Optional[CurrentSaveContext],
    ) -> None:
        if hasattr(self, "_sidebar"):
            if context is None:
                self._sidebar.set_current_save_name(None)
            else:
                self._sidebar.set_current_save_name(
                    context.name,
                    context.display_path,
                )
        if context is None or not hasattr(self, "gui_optimizer"):
            return
        notification_manager = self.gui_optimizer.notification_manager
        if notification_manager:
            notification_manager.show_success(
                f"当前存档已设置为 {context.name}，相关功能将自动使用该存档"
            )
        self._schedule_auto_import_mc_language(context)

    def _on_recent_saves_changed(
        self,
        recent_saves: tuple[RecentSave, ...],
    ) -> None:
        if hasattr(self, "_sidebar"):
            self._sidebar.set_recent_saves(
                [save.to_dict() for save in recent_saves]
            )

    def _activate_current_save(self, path: str) -> None:
        del path
        if hasattr(self, "_sidebar") and self._sidebar.selected_id != "explorer":
            self._sidebar.select_tab("explorer")
            return
        self.view_manager.switch_view("explorer")


__all__ = ["SaveContextUiMixin"]

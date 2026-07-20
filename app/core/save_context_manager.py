"""Current-save selection use cases, independent from Flet controls."""
from __future__ import annotations

from typing import Callable, Dict, List, Mapping, Optional, Protocol

from app.models.save_context import CurrentSaveContext
from app.models.save_store import CurrentSaveStore
from core.types import LogCallback


class SaveConfig(Protocol):
    def get_recent_saves(self) -> List[Dict[str, str]]:
        ...

    def set_recent_saves(self, saves: List[Dict[str, str]]) -> None:
        ...


DirectoryPicker = Callable[[], Optional[str]]
DialogCallback = Callable[[str, str], None]
ActivateSaveCallback = Callable[[str], None]


def _discard_log(message: str, level: str = "INFO") -> None:
    del message, level


class SaveContextManager:
    """Validate selections and persist recent saves around a state store."""

    def __init__(
        self,
        config: SaveConfig,
        store: CurrentSaveStore,
        pick_directory: DirectoryPicker,
        warn_dialog: DialogCallback,
        error_dialog: DialogCallback,
        activate_save: ActivateSaveCallback,
        log: Optional[LogCallback] = None,
    ) -> None:
        self._config = config
        self.store = store
        self._pick_directory = pick_directory
        self._warn_dialog = warn_dialog
        self._error_dialog = error_dialog
        self._activate_save = activate_save
        self._log = log or _discard_log

    def initialize(self) -> None:
        self.store.replace_recent(self._load_recent_saves())

    def get_current_save_context(self) -> Optional[CurrentSaveContext]:
        return self.store.current

    def get_current_save_path(self) -> Optional[str]:
        return self.store.current_path

    def get_recent_saves(self) -> List[Dict[str, str]]:
        return [save.to_dict() for save in self.store.recent]

    def set_current_save_context(self, context: CurrentSaveContext) -> None:
        self.store.select(context)
        self.store.remember(context)
        self._save_recent_saves()
        try:
            self._activate_save(context.display_path)
        except Exception as exc:
            # Explorer activation is best-effort after selection succeeds.
            self._log(f"激活存档浏览器失败: {exc}", "ERROR")

    def set_current_save_path(self, path: Optional[str]) -> None:
        if path is None:
            self.store.clear()
            return
        self.set_current_save_context(CurrentSaveContext.from_path(path))

    def on_import_save(self) -> None:
        try:
            path = self._pick_directory()
            if not path:
                return
            context = CurrentSaveContext.from_path(path)
            if not context.is_valid:
                self._warn_dialog(
                    "提示",
                    "这不是有效存档目录，请选择包含 level.dat 的文件夹。",
                )
                return
            self.set_current_save_context(context)
        except (OSError, ValueError, TypeError) as exc:
            self._error_dialog("错误", f"设置当前存档失败: {exc}")
        except Exception as exc:
            self._error_dialog("错误", f"设置当前存档失败: {exc}")

    def on_recent_save_select(self, path: str) -> None:
        try:
            context = CurrentSaveContext.from_path(path)
            if not context.is_valid:
                self._warn_dialog(
                    "提示",
                    "该最近存档已失效，目录中未找到 level.dat。",
                )
                if self.store.remove_recent(path):
                    self._save_recent_saves()
                return
            self.set_current_save_context(context)
        except (OSError, ValueError, TypeError) as exc:
            self._error_dialog("错误", f"设置当前存档失败: {exc}")
        except Exception as exc:
            self._error_dialog("错误", f"设置当前存档失败: {exc}")

    def _load_recent_saves(self) -> List[Mapping[str, object]]:
        try:
            saves = self._config.get_recent_saves()
            if isinstance(saves, list):
                return [save for save in saves if isinstance(save, Mapping)]
        except (OSError, TypeError, ValueError, KeyError) as exc:
            self._log(f"加载最近存档失败: {exc}", "ERROR")
        except Exception as exc:
            self._log(f"加载最近存档失败: {exc}", "ERROR")
        return []

    def _save_recent_saves(self) -> None:
        try:
            self._config.set_recent_saves(self.get_recent_saves())
        except (OSError, TypeError, ValueError) as exc:
            self._log(f"保存最近存档失败: {exc}", "ERROR")
        except Exception as exc:
            self._log(f"保存最近存档失败: {exc}", "ERROR")

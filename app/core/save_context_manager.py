"""Current-save selection use cases, independent from Flet controls."""
from __future__ import annotations

from typing import Callable, Dict, List, Mapping, Optional, Protocol

from app.models.save_context import CurrentSaveContext
from app.models.save_store import CurrentSaveStore
from core.types import LogCallback


class SaveConfig(Protocol):
    """最近存档持久化端口（通常由 ConfigService 实现）。"""

    def get_recent_saves(self) -> List[Dict[str, str]]:
        """读取最近存档列表。

        Returns:
            含 ``path``/``name`` 的字典列表。
        """
        ...

    def set_recent_saves(self, saves: List[Dict[str, str]]) -> None:
        """替换并持久化最近存档列表。

        Args:
            saves: 待写入的最近存档字典列表。
        """
        ...


DirectoryPicker = Callable[[], Optional[str]]
DialogCallback = Callable[[str, str], None]
ActivateSaveCallback = Callable[[str], None]


def _discard_log(message: str, level: str = "INFO") -> None:
    del message, level


class SaveContextManager:
    """校验选择并围绕状态仓库持久化最近存档。

    组合目录选择、校验、store 更新、配置写盘与浏览器激活；
    不持有 Flet 控件。``activate_save`` 失败不回滚已成功的选择。
    """

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
        """注入配置、状态与 UI 端口。

        Args:
            config: 最近存档读写端口。
            store: 当前/最近存档状态所有者。
            pick_directory: 无参目录选择器，取消返回 None。
            warn_dialog: ``(title, message)`` 警告对话框。
            error_dialog: ``(title, message)`` 错误对话框。
            activate_save: 选择成功后激活资源浏览器的回调。
            log: 可选日志回调；缺省丢弃。
        """
        self._config = config
        self.store = store
        self._pick_directory = pick_directory
        self._warn_dialog = warn_dialog
        self._error_dialog = error_dialog
        self._activate_save = activate_save
        self._log = log or _discard_log

    def initialize(self) -> None:
        """从配置加载最近存档到 store（启动时调用一次）。"""
        self.store.replace_recent(self._load_recent_saves())

    def get_current_save_context(self) -> Optional[CurrentSaveContext]:
        """返回当前存档上下文。

        Returns:
            当前上下文；未选择时为 None。
        """
        return self.store.current

    def get_current_save_path(self) -> Optional[str]:
        """返回当前存档展示路径。

        Returns:
            路径字符串；未选择时为 None。
        """
        return self.store.current_path

    def get_recent_saves(self) -> List[Dict[str, str]]:
        """返回可序列化的最近存档列表副本。

        Returns:
            每项含 ``path`` 与 ``name`` 的字典列表。
        """
        return [save.to_dict() for save in self.store.recent]

    def set_current_save_context(self, context: CurrentSaveContext) -> None:
        """设置当前存档、记住到最近列表并尝试激活浏览器。

        Args:
            context: 已解析的存档上下文（调用方保证有效）。
        """
        self.store.select(context)
        self.store.remember(context)
        self._save_recent_saves()
        try:
            self._activate_save(context.display_path)
        except Exception as exc:
            # Explorer activation is best-effort after selection succeeds.
            self._log(f"激活存档浏览器失败: {exc}", "ERROR")

    def set_current_save_path(self, path: Optional[str]) -> None:
        """按路径设置或清空当前存档。

        Args:
            path: 存档目录；``None`` 时清空当前选择。
        """
        if path is None:
            self.store.clear()
            return
        self.set_current_save_context(CurrentSaveContext.from_path(path))

    def on_import_save(self) -> None:
        """通过目录选择器导入并设为当前存档。

        无效目录（无 level.dat）仅提示警告，不修改状态。
        """
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
        """从最近列表选择存档。

        失效路径会警告并从最近列表移除后写回配置。

        Args:
            path: 最近列表中的存档路径。
        """
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

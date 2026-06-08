"""World info tab mixin for ExplorerView."""
from pathlib import Path
from typing import Any

import flet as ft

from app.ui.theme import THEME
from app.ui.views.explorer.world_info_panel import WorldInfoPanel


class WorldInfoTabMixin:
    """Build and handle the Explorer world-info tab."""

    def _build_world_info_tab(self) -> None:
        self._world_info_panel = WorldInfoPanel(
            self._t,
            on_backup_click=self._create_backup,
            on_restore_click=self._restore_backup,
        )
        self._tab_world_info.content = self._world_info_panel

    def _create_backup(self, e: Any = None) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先设置当前存档")
                return
            backup_path = self.world_session.create_backup()
            if backup_path:
                self.app.info_dialog(
                    "备份成功",
                    f"存档已备份到：\n{backup_path}",
                )
            else:
                self.app.warn_dialog("备份失败", "创建备份失败，请查看日志")
        except Exception as ex:
            self.app.handle_exception(ex, title="创建备份失败")

    def _restore_backup(self, e: Any = None) -> None:
        try:
            if not self.world_session:
                self.app.warn_dialog("提示", "请先设置当前存档")
                return
            backups = self.world_session.list_backups()
            if not backups:
                self.app.info_dialog("提示", "未找到可用的备份")
                return

            def _show_backup_dialog() -> None:
                import datetime

                backup_options = []
                for backup in backups:
                    stat = backup.stat()
                    size_mb = stat.st_size / (1024 * 1024)
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                    label = f"{backup.name} ({mtime.strftime('%Y-%m-%d %H:%M:%S')} - {size_mb:.1f} MB)"
                    backup_options.append(ft.dropdown.Option(str(backup), label))

                backup_dropdown = ft.Dropdown(
                    label="选择备份",
                    options=backup_options,
                    value=str(backups[0]),
                    expand=True,
                )

                replace_switch = ft.Switch(
                    label="替换当前存档（危险，将先备份当前存档）",
                    value=False,
                )

                dialog = ft.AlertDialog(
                    title=ft.Text("选择备份", color=THEME.text_primary),
                    content=ft.Column([
                        backup_dropdown,
                        replace_switch,
                    ], tight=True, spacing=12),
                    actions=[],
                )

                def _do_restore(_: Any) -> None:
                    try:
                        selected_backup = Path(backup_dropdown.value)
                        replace = replace_switch.value
                        if self.world_session.restore_backup(selected_backup, replace):
                            dialog.open = False
                            self.page.update()
                            if replace:
                                self.app.info_dialog("恢复成功", "已从备份恢复，当前存档已更新")
                                self._load_world()
                            else:
                                self.app.info_dialog("恢复成功", "备份已恢复为副本")
                        else:
                            self.app.warn_dialog("恢复失败", "恢复备份失败，请查看日志")
                    except Exception as ex:
                        self.app.handle_exception(ex, title="恢复备份失败")

                def _cancel(_: Any) -> None:
                    dialog.open = False
                    self.page.update()

                dialog.actions = [
                    ft.TextButton("取消", on_click=_cancel),
                    ft.TextButton("恢复", on_click=_do_restore),
                ]
                self.page.overlay.append(dialog)
                dialog.open = True
                self.page.update()

            _show_backup_dialog()
        except Exception as ex:
            self.app.handle_exception(ex, title="恢复备份失败")

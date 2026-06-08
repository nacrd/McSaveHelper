"""Save Repair View - 存档修复视图

支持存档检测（只读诊断）和存档修复（修改文件）。
"""
import threading
from pathlib import Path
from typing import TYPE_CHECKING, List

import flet as ft

from app.ui.theme import THEME, mc_border
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field, checkbox, current_save_field
from app.ui.components.cards import card, section_title
from app.ui.components.layout import page_header
from app.ui.utils import run_on_ui
from app.services.save_repair_service import (
    SaveRepairService,
    RepairReport,
    DetectReport,
    IssueLevel,
)

if TYPE_CHECKING:
    from app.application import Application


_LEVEL_COLORS = {
    IssueLevel.INFO: THEME.text_secondary,
    IssueLevel.WARNING: THEME.warning,
    IssueLevel.ERROR: THEME.error,
    IssueLevel.FIXED: THEME.success,
}


class SaveRepairView(ft.Column):
    """存档修复视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=20, scroll=ft.ScrollMode.AUTO)
        self.app = app
        self.service = SaveRepairService()
        self.expand = True

        self._busy = False

        # 配置选项
        self._world_path_field = current_save_field(
            hint_text="请通过侧边栏「设置当前存档」设置要修复的当前存档目录",
        )
        self._fix_chunks_checkbox = checkbox("修复区块", value=True)
        self._fix_players_checkbox = checkbox("修复玩家数据", value=True)
        self._fix_level_dat_checkbox = checkbox("修复 level.dat", value=True)
        self._backup_checkbox = checkbox("创建备份（推荐）", value=True)

        # 日志面板
        self._log_column = ft.Column(
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
            height=200,
        )

        # 世界信息展示
        self._world_info_text = ft.Text(
            "",
            size=12,
            color=THEME.text_secondary,
            selectable=True,
        )
        self._world_info_card: ft.Container = ft.Container(visible=False)

        # 检测结果
        self._detect_result_text = ft.Text(
            "",
            size=13,
            color=THEME.text_secondary,
            selectable=True,
        )
        self._detect_result_card: ft.Container = ft.Container(visible=False)

        # 修复结果
        self._result_text = ft.Text(
            "",
            size=13,
            color=THEME.text_secondary,
            selectable=True,
        )

        # 按钮
        self._detect_btn = btn_primary("检测存档", on_click=self._start_detect)
        self._repair_btn = btn_primary("开始修复", on_click=self._start_repair)
        self._cancel_btn = btn_ghost("取消", on_click=self._cancel)
        self._cancel_btn.visible = False

        self._build_ui()

    def _build_ui(self) -> None:
        header = page_header(
            "存档修复",
            ft.Text("检测存档状态、修复损坏的区块、玩家数据、level.dat", size=12, color=THEME.text_muted),
            icon="🔧",
        )

        config_card = card(
            ft.Column(
                [
                    section_title("当前存档"),
                    self._world_path_field,
                    ft.Container(height=12),
                    section_title("操作"),
                    ft.Row(
                        [self._detect_btn, self._repair_btn, self._cancel_btn],
                        spacing=12,
                    ),
                    ft.Container(height=12),
                    section_title("修复选项"),
                    ft.Column(
                        [
                            self._fix_chunks_checkbox,
                            self._fix_players_checkbox,
                            self._fix_level_dat_checkbox,
                            self._backup_checkbox,
                        ],
                        spacing=8,
                    ),
                ],
                spacing=12,
            )
        )

        # 世界信息卡片（检测后显示）
        self._world_info_card = ft.Container(
            content=card(
                ft.Column(
                    [
                        section_title("世界信息"),
                        ft.Container(
                            content=self._world_info_text,
                            padding=12,
                            bgcolor=THEME.bg_secondary,
                            border_radius=8,
                        ),
                    ],
                    spacing=12,
                )
            ),
            visible=False,
        )

        # 检测结果卡片（检测后显示）
        self._detect_result_card = ft.Container(
            content=card(
                ft.Column(
                    [
                        section_title("检测结果"),
                        ft.Container(
                            content=self._detect_result_text,
                            padding=12,
                            bgcolor=THEME.bg_secondary,
                            border_radius=8,
                        ),
                    ],
                    spacing=12,
                )
            ),
            visible=False,
        )

        result_card = card(
            ft.Column(
                [
                    section_title("修复结果"),
                    ft.Container(
                        content=self._result_text,
                        padding=12,
                        bgcolor=THEME.bg_secondary,
                        border_radius=8,
                    ),
                ],
                spacing=12,
            )
        )

        log_card = card(
            ft.Column(
                [
                    section_title("执行日志"),
                    ft.Container(
                        content=self._log_column,
                        padding=8,
                        bgcolor=THEME.bg_secondary,
                        border_radius=4,
                        border=mc_border(1),
                    ),
                ],
                spacing=12,
            )
        )

        info_card = card(
            ft.Column(
                [
                    section_title("使用说明"),
                    ft.Text(
                        "• 检测存档：只读扫描，报告世界信息和潜在问题，不修改任何文件\n"
                        "• 修复区块：检测损坏的区块数据，隔离无法读取的区域文件\n"
                        "• 修复玩家数据：验证并补充缺失的必需字段（Pos/Health 等）\n"
                        "• 修复 level.dat：检查并从备份恢复，补充缺失的世界配置字段\n"
                        "• 建议先执行检测，确认问题后再进行修复",
                        size=12,
                        color=THEME.text_secondary,
                    ),
                ],
                spacing=12,
            )
        )

        self.controls = [
            header,
            ft.Container(height=8),
            config_card,
            self._world_info_card,
            self._detect_result_card,
            result_card,
            log_card,
            info_card,
        ]

        self._world_path_field.expand = True

    # ── 事件处理 ──────────────────────────────────────────

    def _validate_path(self) -> Path:
        world_path = self._world_path_field.value
        if not world_path:
            raise ValueError("请先通过侧边栏设置当前存档目录")
        return Path(world_path)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._detect_btn.disabled = busy
        self._repair_btn.disabled = busy
        self._cancel_btn.visible = busy
        self._cancel_btn.disabled = False
        try:
            self._detect_btn.update()
            self._repair_btn.update()
            self._cancel_btn.update()
        except Exception:
            pass

    def _start_detect(self, e: ft.ControlEvent) -> None:
        if self._busy:
            self.app.warn_dialog("提示", "操作正在进行中，请稍候")
            return
        try:
            world_path = self._validate_path()
        except ValueError as ex:
            self.app.warn_dialog("提示", str(ex))
            return

        self._set_busy(True)
        self._log_column.controls.clear()
        self._log_column.update()
        self._detect_result_card.visible = False
        self._detect_result_card.update()
        self._world_info_card.visible = False
        self._world_info_card.update()

        threading.Thread(
            target=self._detect_thread,
            args=(world_path,),
            daemon=True,
        ).start()

    def _start_repair(self, e: ft.ControlEvent) -> None:
        if self._busy:
            self.app.warn_dialog("提示", "操作正在进行中，请稍候")
            return
        try:
            world_path = self._validate_path()
        except ValueError as ex:
            self.app.warn_dialog("提示", str(ex))
            return

        self._set_busy(True)
        self._result_text.value = ""
        self._result_text.update()
        self._log_column.controls.clear()
        self._log_column.update()

        repair_options = {
            "fix_chunks": bool(self._fix_chunks_checkbox.value),
            "fix_players": bool(self._fix_players_checkbox.value),
            "fix_level_dat": bool(self._fix_level_dat_checkbox.value),
            "backup": bool(self._backup_checkbox.value),
        }

        threading.Thread(
            target=self._repair_thread,
            args=(world_path, repair_options),
            daemon=True,
        ).start()

    def _cancel(self, e: ft.ControlEvent) -> None:
        self.service.cancel()
        self._cancel_btn.disabled = True
        self._cancel_btn.update()

    # ── 检测线程 ──────────────────────────────────────────

    def _detect_thread(self, world_path: Path) -> None:
        try:
            run_on_ui(self.app.page, self.app.show_progress, "正在检测存档...")

            def progress_callback(value: float, msg: str) -> None:
                run_on_ui(self.app.page, self.app.update_progress_with_task, msg or "检测中", value)

            def log_callback(msg: str, level: str) -> None:
                run_on_ui(self.app.page, self._append_log, msg, level)

            report = self.service.detect_world(
                world_path=world_path,
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

            run_on_ui(self.app.page, self._show_detect_report, report)

        except Exception as ex:
            def _show_error(error: Exception) -> None:
                self._detect_result_text.value = f"检测失败: {error}"
                self._detect_result_text.update()
                self._detect_result_card.visible = True
                self._detect_result_card.update()
                self.app.error_dialog("错误", f"检测失败: {error}")
            run_on_ui(self.app.page, _show_error, ex)

        finally:
            def _finish() -> None:
                self.app.hide_progress()
                self._set_busy(False)
            run_on_ui(self.app.page, _finish)

    def _show_detect_report(self, report: DetectReport) -> None:
        info = report.world_info

        # 世界信息
        info_lines: List[str] = []
        if info.world_name:
            info_lines.append(f"名称: {info.world_name}")
        if info.version_name:
            info_lines.append(f"版本: {info.version_name} (DataVersion {info.data_version})")
        if info.game_type_name:
            info_lines.append(f"模式: {info.game_type_name}")
        info_lines.append(f"难度: {info.difficulty_name}")
        info_lines.append(f"种子: {info.seed}")
        info_lines.append(f"出生点: ({info.spawn_pos[0]}, {info.spawn_pos[1]}, {info.spawn_pos[2]})")
        if info.play_time_ticks > 0:
            hours = info.play_time_ticks / 72000
            info_lines.append(f"游戏时间: {hours:.1f} 小时")
        info_lines.append(f"存档大小: {info.world_size_mb:.1f} MB ({info.total_files} 文件)")
        info_lines.append(f"维度: {', '.join(info.dimensions) if info.dimensions else '无'}")
        info_lines.append(f"区域文件: {info.region_count}  区块: ~{info.total_chunks}")
        info_lines.append(f"玩家数量: {info.player_count}")

        self._world_info_text.value = "\n".join(info_lines)
        self._world_info_text.update()
        self._world_info_card.visible = True
        self._world_info_card.update()

        # 检测结果
        result_lines: List[str] = []

        if report.cancelled:
            result_lines.append("(操作已取消)\n")

        result_lines.append(f"区块: {report.chunks_checked} 检查 / {report.chunks_damaged} 损坏")

        if report.unreadable_regions:
            result_lines.append(f"无法读取的区域文件: {len(report.unreadable_regions)}")
            for name in report.unreadable_regions[:10]:
                result_lines.append(f"  {name}")
            if len(report.unreadable_regions) > 10:
                result_lines.append(f"  ... 共 {len(report.unreadable_regions)} 个")

        result_lines.append(f"玩家: {report.players_checked} 检查 / {report.players_with_issues} 有问题")
        if report.player_issues:
            for pname, pissues in list(report.player_issues.items())[:5]:
                result_lines.append(f"  {pname}: {', '.join(pissues)}")
            if len(report.player_issues) > 5:
                result_lines.append(f"  ... 共 {len(report.player_issues)} 个玩家")

        level_status = "正常" if report.level_dat_ok else "异常"
        result_lines.append(f"level.dat: {level_status}")
        for issue in report.level_dat_issues:
            result_lines.append(f"  {issue}")

        result_lines.append(f"\n耗时: {report.elapsed_seconds:.1f}s")

        if report.has_problems:
            result_lines.append("\n发现异常，建议执行修复。")
        else:
            result_lines.append("\n存档状态良好，未发现问题。")

        self._detect_result_text.value = "\n".join(result_lines)
        self._detect_result_text.update()
        self._detect_result_card.visible = True
        self._detect_result_card.update()

    # ── 修复线程 ──────────────────────────────────────────

    def _repair_thread(self, world_path: Path, repair_options: dict) -> None:
        try:
            run_on_ui(self.app.page, self.app.show_progress, "正在修复存档...")

            def progress_callback(value: float, msg: str) -> None:
                run_on_ui(self.app.page, self.app.update_progress_with_task, msg or "修复中", value)

            def log_callback(msg: str, level: str) -> None:
                run_on_ui(self.app.page, self._append_log, msg, level)

            report = self.service.repair_world(
                world_path=world_path,
                fix_chunks=repair_options["fix_chunks"],
                fix_players=repair_options["fix_players"],
                fix_level_dat=repair_options["fix_level_dat"],
                backup=repair_options["backup"],
                progress_callback=progress_callback,
                log_callback=log_callback,
            )

            run_on_ui(self.app.page, self._show_repair_report, report)

        except Exception as ex:
            def _show_error(error: Exception) -> None:
                self._result_text.value = f"修复失败: {error}"
                self._result_text.update()
                self.app.error_dialog("错误", f"修复失败: {error}")
            run_on_ui(self.app.page, _show_error, ex)

        finally:
            def _finish() -> None:
                self.app.hide_progress()
                self._set_busy(False)
            run_on_ui(self.app.page, _finish)

    # ── 结果展示 ──────────────────────────────────────────

    def _show_repair_report(self, report: RepairReport) -> None:
        lines: List[str] = []

        if report.cancelled:
            lines.append("(操作已取消)\n")

        lines.append(f"区块检查: {report.chunks_checked}")
        if report.chunks_damaged > 0:
            lines.append(f"区块损坏: {report.chunks_damaged}")
        if report.chunks_quarantined_regions > 0:
            lines.append(f"区域文件隔离: {report.chunks_quarantined_regions}")

        lines.append(f"玩家检查: {report.players_checked}")
        if report.players_fixed > 0:
            lines.append(f"玩家修复: {report.players_fixed}")
        if report.players_quarantined > 0:
            lines.append(f"玩家隔离: {report.players_quarantined}")

        level_status = "正常"
        if report.level_dat_fixed:
            level_status = "已修复"
            if report.level_dat_repaired_fields:
                level_status += f" ({', '.join(report.level_dat_repaired_fields)})"
        lines.append(f"level.dat: {level_status}")

        if report.backup_path:
            lines.append(f"\n备份: {report.backup_path}")

        lines.append(f"\n耗时: {report.elapsed_seconds:.1f}s")

        self._result_text.value = "\n".join(lines)
        self._result_text.update()

        if not report.cancelled:
            self.app.info_dialog("完成", "存档修复完成！")

    def _append_log(self, msg: str, level: str) -> None:
        color_map = {
            "INFO": THEME.text_secondary,
            "WARNING": THEME.warning,
            "ERROR": THEME.error,
            "SUCCESS": THEME.success,
        }
        color = color_map.get(level.upper(), THEME.text_secondary)
        prefix_map = {
            "INFO": "[INFO]",
            "WARNING": "[WARN]",
            "ERROR": "[ERR]",
            "SUCCESS": "[OK]",
        }
        prefix = prefix_map.get(level.upper(), "[INFO]")

        log_entry = ft.Text(
            f"{prefix} {msg}",
            size=11,
            color=color,
            selectable=True,
            font_family="monospace",
        )
        self._log_column.controls.append(log_entry)
        try:
            self._log_column.update()
        except Exception:
            pass

    def on_save_selected(self, path: str) -> None:
        """统一入口设置当前存档回调"""
        try:
            self._world_path_field.value = path
            self._world_path_field.update()
            # 隐藏之前的结果
            self._world_info_card.visible = False
            self._world_info_card.update()
            self._detect_result_card.visible = False
            self._detect_result_card.update()
        except Exception:
            pass

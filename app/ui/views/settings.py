"""Settings View —— 应用配置界面"""
import flet as ft
from typing import TYPE_CHECKING, Dict

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost, btn_success, btn_danger
from app.ui.components.fields import text_field, checkbox, label
from app.ui.components.cards import card, section_title
from app.ui.components.uuid_table import UUIDMappingTable

if TYPE_CHECKING:
    from app.application import Application


class SettingsView(ft.Column):
    """配置设置视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app: "Application" = app
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()
        self._build_general_card()
        self._build_ui_card()
        self._build_batch_card()
        self._build_uuid_card()
        self._build_cleanup_card()
        self._build_action_card()

    # ─── 通用设置 ───────────────────────────────

    def _build_general_card(self) -> None:
        cfg = self.app.config
        s = ft.Column(spacing=0)
        s.controls.append(section_title(self._t("settings.general.title", "通用设置")))

        self._version_var = checkbox(
            self._t("settings.general.version_detection", "启用版本自动检测"),
            value=cfg.version_detection,
        )
        s.controls.append(ft.Container(content=self._version_var,
                                       padding=ft.Padding(left=20, right=20, top=10)))

        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.general.api_timeout", "API 超时 (秒)")),
                text_field(value=str(cfg.api_timeout), width=100, expand=False),
            ], spacing=4),
            padding=ft.Padding(left=20, right=20, bottom=20, top=10),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=16)))

    # ─── 界面设置 ───────────────────────────────

    def _build_ui_card(self) -> None:
        cfg = self.app.config
        s = ft.Column(spacing=0)
        s.controls.append(section_title(self._t("settings.ui.title", "界面设置")))

        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.theme", "主题")),
                ft.Dropdown(
                    options=[ft.dropdown.Option("dark"), ft.dropdown.Option("light")],
                    value=cfg.theme,
                    width=120, border_color=THEME.border_standard, text_size=13,
                ),
            ], spacing=4),
            padding=ft.Padding(left=20, right=20, bottom=10, top=10),
        ))

        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.language", "语言")),
                ft.Dropdown(
                    options=[ft.dropdown.Option("zh_CN"), ft.dropdown.Option("en_US")],
                    value=cfg.language,
                    width=120, border_color=THEME.border_standard, text_size=13,
                ),
            ], spacing=4),
            padding=ft.Padding(left=20, right=20, bottom=10),
        ))

        self._auto_clear_var = checkbox(
            self._t("settings.ui.auto_clear_log", "自动清除旧日志"),
            value=cfg.ui_settings.get("auto_clear_log", False),
        )
        s.controls.append(ft.Container(content=self._auto_clear_var,
                                       padding=ft.Padding(left=20, right=20, bottom=20)))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=16)))

    # ─── 批量处理 ───────────────────────────────

    def _build_batch_card(self) -> None:
        cfg = self.app.config
        s = ft.Column(spacing=0)
        s.controls.append(section_title(self._t("settings.batch.title", "批量处理")))

        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.batch.max_concurrent", "最大并发处理数 (1‑16)")),
                text_field(value=str(cfg.max_concurrent), width=100, expand=False),
            ], spacing=4),
            padding=ft.Padding(left=20, right=20, bottom=10, top=10),
        ))

        self._preserve_var = checkbox(
            self._t("settings.batch.preserve_structure", "保留原始文件结构"),
            value=cfg.batch_processing.get("preserve_structure", True),
        )
        s.controls.append(ft.Container(content=self._preserve_var,
                                       padding=ft.Padding(left=20, right=20, bottom=20)))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=16)))

    # ─── UUID 映射 ───────────────────────────────

    def _build_uuid_card(self) -> None:
        cfg = self.app.config
        s = ft.Column(spacing=0)
        s.controls.append(section_title(self._t("settings.uuid.title", "自定义 UUID 映射")))

        s.controls.append(ft.Container(
            content=ft.Text(
                self._t("settings.uuid.description",
                        "在此添加玩家名与 UUID 的映射，用于离线模式下的玩家数据转换。"),
                size=12, color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=10, top=10),
        ))

        self._mapping_table: UUIDMappingTable = UUIDMappingTable(
            mappings=cfg.custom_uuid_mappings,
            on_mappings_change=self._on_mappings_change,
        )
        s.controls.append(ft.Container(
            content=self._mapping_table,
            padding=ft.Padding(left=20, right=20, bottom=20),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=16)))

    # ─── 清理模式 ───────────────────────────────

    def _build_cleanup_card(self) -> None:
        cfg = self.app.config
        s = ft.Column(spacing=0)
        s.controls.append(section_title(self._t("settings.cleanup.title", "清理模式")))

        s.controls.append(ft.Container(
            content=ft.Text(
                self._t("settings.cleanup.description",
                        "转换完成后自动删除的文件/目录模式（每行一个，支持通配符）"),
                size=12, color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, bottom=10, top=10),
        ))

        patterns = cfg.cleanup_patterns
        self._cleanup_field = ft.TextField(
            value="\n".join(patterns) if isinstance(patterns, list) else "",
            multiline=True, min_lines=4, max_lines=8,
            border_color=THEME.border_standard, text_size=13,
            bgcolor="rgba(255,255,255,0.02)", border_radius=6,
        )
        s.controls.append(ft.Container(content=self._cleanup_field,
                                       padding=ft.Padding(left=20, right=20)))

        s.controls.append(ft.Container(
            content=btn_ghost(
                self._t("settings.cleanup.restore_defaults", "恢复默认"),
                width=120, height=32,
                on_click=lambda e: self._restore_default_cleanup(),
            ),
            padding=ft.Padding(left=20, right=20, bottom=20, top=10),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=16)))

    # ─── 操作按钮 ───────────────────────────────

    def _build_action_card(self) -> None:
        btn_row = ft.Row([
            btn_success(
                self._t("settings.actions.save", "💾 保存设置"), width=140,
                on_click=lambda e: self._save(),
            ),
            ft.Button(
                content=self._t("settings.actions.reset", "↻ 重置为默认"),
                width=140, height=38,
                style=ft.ButtonStyle(
                    color=THEME.text_primary, bgcolor=THEME.warning,
                    shape=ft.RoundedRectangleBorder(radius=6),
                ),
                on_click=lambda e: self._reset(),
            ),
            btn_ghost(
                self._t("settings.actions.cancel", "取消"), width=100, height=38,
                on_click=lambda e: self._cancel(),
            ),
        ], spacing=10)
        c = card(ft.Column(spacing=0), padding=0)
        c.content = ft.Container(content=btn_row, padding=20)
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=24)))

    # ─── 回调 ──────────────────────────────────

    def _on_mappings_change(self, mappings: Dict[str, str]) -> None:
        self.app.config.custom_uuid_mappings = mappings

    def _restore_default_cleanup(self) -> None:
        self._cleanup_field.value = "\n".join(["*.log", "cache/", "logs/"])
        self._cleanup_field.update()

    def _save(self) -> None:
        c = self.app.config
        c._config["version_detection"] = self._version_var.value
        c._config["ui_settings"]["auto_clear_log"] = self._auto_clear_var.value
        c._config["ui_settings"]["preserve_structure"] = self._preserve_var.value
        c.cleanup_patterns = [x.strip() for x in self._cleanup_field.value.split("\n") if x.strip()]
        c.save()
        self.app.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t("settings.messages.save_success", "设置已保存"),
        )

    def _reset(self) -> None:
        self.app.config.reset_config()
        self.app.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t("settings.messages.reset_success", "已恢复默认设置"),
        )
        self._build()

    def _cancel(self) -> None:
        self._build()

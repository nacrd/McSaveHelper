"""Settings view - application configuration"""
import flet as ft
from typing import TYPE_CHECKING, List, Dict
from ui.constants import COLORS
from ui.widgets import card, section_title, label, btn_primary, btn_ghost, btn_success, btn_danger
from ui.widgets import text_field, checkbox
from core.config import config_manager
from core.i18n import t

if TYPE_CHECKING:
    from ui.app import App


class SettingsView(ft.Column):
    def __init__(self, app: "App"):
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self.app = app
        self.cfg = config_manager
        self._build()

    def _build(self):
        self.controls.clear()
        self._build_general_card()
        self._build_ui_card()
        self._build_batch_card()
        self._build_uuid_card()
        self._build_cleanup_card()
        self._build_action_card()

    def _build_general_card(self):
        c = card(ft.Column(spacing=0), padding=0)
        s = ft.Column(spacing=0)
        s.controls.append(section_title(t("settings.general.title", "通用设置")))

        self._version_var = checkbox(
            t("settings.general.version_detection", "启用版本自动检测"),
            value=self.cfg.config.get("version_detection", True),
        )
        s.controls.append(ft.Container(content=self._version_var, padding=ft.padding.only(left=20, right=20, top=10)))

        s.controls.append(
            ft.Container(
                content=ft.Column([
                    label(t("settings.general.api_timeout", "API 超时 (秒)")),
                    text_field(value=str(self.cfg.config.get("api_timeout", 10)), width=100, expand=False),
                ], spacing=4),
                padding=ft.padding.only(left=20, right=20, bottom=20, top=10),
            )
        )
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.padding.only(bottom=16)))

    def _build_ui_card(self):
        c = card(ft.Column(spacing=0), padding=0)
        s = ft.Column(spacing=0)
        s.controls.append(section_title(t("settings.ui.title", "界面设置")))

        s.controls.append(
            ft.Container(
                content=ft.Column([
                    label(t("settings.ui.theme", "主题")),
                    ft.Dropdown(
                        options=[ft.dropdown.Option("dark"), ft.dropdown.Option("light")],
                        value=self.cfg.config.get("ui_settings", {}).get("theme", "dark"),
                        width=120, border_color=COLORS["border_standard"], text_size=13,
                    ),
                ], spacing=4),
                padding=ft.padding.only(left=20, right=20, bottom=10, top=10),
            )
        )

        s.controls.append(
            ft.Container(
                content=ft.Column([
                    label(t("settings.ui.language", "语言")),
                    ft.Dropdown(
                        options=[ft.dropdown.Option("zh_CN"), ft.dropdown.Option("en_US")],
                        value=self.cfg.config.get("ui_settings", {}).get("language", "zh_CN"),
                        width=120, border_color=COLORS["border_standard"], text_size=13,
                    ),
                ], spacing=4),
                padding=ft.padding.only(left=20, right=20, bottom=10),
            )
        )

        self._auto_clear_var = checkbox(
            t("settings.ui.auto_clear_log", "自动清除旧日志"),
            value=self.cfg.config.get("ui_settings", {}).get("auto_clear_log", False),
        )
        s.controls.append(ft.Container(content=self._auto_clear_var, padding=ft.padding.only(left=20, right=20, bottom=20)))
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.padding.only(bottom=16)))

    def _build_batch_card(self):
        c = card(ft.Column(spacing=0), padding=0)
        s = ft.Column(spacing=0)
        s.controls.append(section_title(t("settings.batch.title", "批量处理")))

        s.controls.append(
            ft.Container(
                content=ft.Column([
                    label(t("settings.batch.max_concurrent", "最大并发处理数 (1‑16)")),
                    text_field(
                        value=str(self.cfg.config.get("batch_processing", {}).get("max_concurrent", 2)),
                        width=100, expand=False,
                    ),
                ], spacing=4),
                padding=ft.padding.only(left=20, right=20, bottom=10, top=10),
            )
        )

        self._preserve_var = checkbox(
            t("settings.batch.preserve_structure", "保留原始文件结构"),
            value=self.cfg.config.get("batch_processing", {}).get("preserve_structure", True),
        )
        s.controls.append(ft.Container(content=self._preserve_var, padding=ft.padding.only(left=20, right=20, bottom=20)))
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.padding.only(bottom=16)))

    def _build_uuid_card(self):
        c = card(ft.Column(spacing=0), padding=0)
        s = ft.Column(spacing=0)
        s.controls.append(section_title(t("settings.uuid.title", "自定义 UUID 映射")))

        s.controls.append(
            ft.Container(
                content=ft.Text(
                    t("settings.uuid.description", "在此添加玩家名与 UUID 的映射，用于离线模式下的玩家数据转换。"),
                    size=12, color=COLORS["text_muted"],
                ),
                padding=ft.padding.only(left=20, right=20, bottom=10, top=10),
            )
        )
        from ui.widgets import UUIDMappingTable
        self._mapping_table = UUIDMappingTable(
            mappings=self.cfg.config.get("custom_uuid_mappings", {}),
            on_mappings_change=self._on_mappings_change,
        )
        s.controls.append(ft.Container(content=self._mapping_table, padding=ft.padding.only(left=20, right=20, bottom=20)))
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.padding.only(bottom=16)))

    def _build_cleanup_card(self):
        c = card(ft.Column(spacing=0), padding=0)
        s = ft.Column(spacing=0)
        s.controls.append(section_title(t("settings.cleanup.title", "清理模式")))

        s.controls.append(
            ft.Container(
                content=ft.Text(
                    t("settings.cleanup.description", "转换完成后自动删除的文件/目录模式（每行一个，支持通配符）"),
                    size=12, color=COLORS["text_muted"],
                ),
                padding=ft.padding.only(left=20, right=20, bottom=10, top=10),
            )
        )

        patterns = self.cfg.config.get("cleanup_patterns", [])
        self._cleanup_field = ft.TextField(
            value="\n".join(patterns) if isinstance(patterns, list) else "",
            multiline=True, min_lines=4, max_lines=8,
            border_color=COLORS["border_standard"], text_size=13,
            bgcolor="rgba(255,255,255,0.02)", border_radius=6,
        )
        s.controls.append(ft.Container(content=self._cleanup_field, padding=ft.padding.only(left=20, right=20)))

        s.controls.append(
            ft.Container(
                content=btn_ghost(t("settings.cleanup.restore_defaults", "恢复默认"), width=120, height=32,
                                  on_click=lambda e: self._restore_default_cleanup()),
                padding=ft.padding.only(left=20, right=20, bottom=20, top=10),
            )
        )
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.padding.only(bottom=16)))

    def _build_action_card(self):
        c = card(ft.Column(spacing=0), padding=0)
        btn_row = ft.Row([
            btn_success(t("settings.actions.save", "💾 保存设置"), width=140, on_click=lambda e: self._save()),
            ft.Button(
                content=t("settings.actions.reset", "↻ 重置为默认"), width=140, height=38,
                style=ft.ButtonStyle(color=COLORS["text_primary"], bgcolor=COLORS["warning"],
                                     shape=ft.RoundedRectangleBorder(radius=6)),
                on_click=lambda e: self._reset(),
            ),
            btn_ghost(t("settings.actions.cancel", "取消"), width=100, height=38,
                      on_click=lambda e: self._cancel()),
        ], spacing=10)
        c.content = ft.Container(content=btn_row, padding=20)
        self.controls.append(ft.Container(content=c, padding=ft.padding.only(bottom=24)))

    def _on_mappings_change(self, mappings: Dict[str, str]):
        self.cfg.config["custom_uuid_mappings"] = mappings

    def _restore_default_cleanup(self):
        self._cleanup_field.value = "\n".join(["*.log", "cache/", "logs/"])
        self._cleanup_field.update()

    def _save(self):
        try:
            self.cfg.config["version_detection"] = self._version_var.value
            self.cfg.config["ui_settings"]["auto_clear_log"] = self._auto_clear_var.value
            self.cfg.config["batch_processing"]["preserve_structure"] = self._preserve_var.value
            text = self._cleanup_field.value.strip()
            self.cfg.config["cleanup_patterns"] = [p.strip() for p in text.splitlines() if p.strip()]
            self.cfg.save_config()
            d = ft.AlertDialog(title=ft.Text(t("common.save", "保存成功")), content=ft.Text(t("messages.settings_saved", "设置已保存")),
                               actions=[ft.TextButton(content=t("dialogs.ok", "确定"), style=ft.ButtonStyle(color=COLORS["accent"]))],
                               open=True)
            self.app.page.open(d)
        except Exception as exc:
            d = ft.AlertDialog(title=ft.Text(t("dialogs.error", "保存失败")), content=ft.Text(str(exc)),
                               actions=[ft.TextButton(content=t("dialogs.ok", "确定"), style=ft.ButtonStyle(color=COLORS["error"]))],
                               open=True)
            self.app.page.open(d)

    def _reset(self):
        from core.config import ConfigSchema
        default_config = {}
        for key, fd in ConfigSchema.BASE_SCHEMA.items():
            if key == "version":
                default_config[key] = fd["default"]
            elif "schema" in fd:
                default_config[key] = {}
                for sk, sfd in fd["schema"].items():
                    default_config[key][sk] = sfd["default"]
            else:
                default_config[key] = fd["default"]
        self.cfg.config.update(default_config)
        self._rebuild()
        d = ft.AlertDialog(title=ft.Text(t("settings.actions.reset", "已重置")), content=ft.Text(t("messages.settings_reset", "已重置为默认设置")),
                           actions=[ft.TextButton(content=t("dialogs.ok", "确定"), style=ft.ButtonStyle(color=COLORS["accent"]))],
                           open=True)
        self.app.page.open(d)

    def _cancel(self):
        self.cfg.__init__()
        self._rebuild()
        d = ft.AlertDialog(title=ft.Text(t("common.cancel", "已取消")), content=ft.Text(t("messages.changes_discarded", "更改已丢弃")),
                           actions=[ft.TextButton(content=t("dialogs.ok", "确定"), style=ft.ButtonStyle(color=COLORS["accent"]))],
                           open=True)
        self.app.page.open(d)

    def _rebuild(self):
        self._build()
        self.update()

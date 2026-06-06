"""Settings View —— 应用配置界面"""
import flet as ft
from pathlib import Path
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
        self._build_item_mapping_card()
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
            on_change=lambda e: setattr(self.app.config.migration, 'version_detection', e.control.value),
        )
        s.controls.append(ft.Container(content=self._version_var,
                                       padding=ft.Padding(left=20, right=20, top=10)))

        self._api_timeout_field = text_field(value=str(cfg.api_timeout), width=100, expand=False,
                                             on_change=lambda e: self._on_api_timeout_change(e))
        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.general.api_timeout", "API 超时 (秒)")),
                self._api_timeout_field,
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

        self._theme_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option("dark"), ft.dropdown.Option("light")],
            value=cfg.theme,
            width=120, border_color=THEME.border_standard, text_size=13,
        )
        self._theme_dropdown.on_change = lambda e: self._on_theme_change(e.control.value)
        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.theme", "主题")),
                self._theme_dropdown,
            ], spacing=4),
            padding=ft.Padding(left=20, right=20, bottom=10, top=10),
        ))

        self._lang_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option("zh_CN"), ft.dropdown.Option("en_US")],
            value=cfg.language,
            width=120, border_color=THEME.border_standard, text_size=13,
        )
        self._lang_dropdown.on_change = lambda e: self._on_language_change(e.control.value)
        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.language", "语言")),
                self._lang_dropdown,
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

        self._max_concurrent_field = text_field(value=str(cfg.max_concurrent), width=100, expand=False)
        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.batch.max_concurrent", "最大并发处理数 (1‑16)")),
                self._max_concurrent_field,
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

    def _build_item_mapping_card(self) -> None:
        s = ft.Column(spacing=0)
        s.controls.append(section_title("自定义物品 ID 映射"))
        s.controls.append(ft.Container(
            content=ft.Text(
                "支持导入外部 JSON 映射、从模组 JAR 提取语言文件，或手动添加单条物品名称映射。",
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=20, right=20, top=10, bottom=10),
        ))

        self._item_id_field = text_field(label="物品 ID", hint_text="modid:item_name", expand=False, width=220)
        self._item_name_field = text_field(label="显示名称", hint_text="显示在物品栏中的名称", expand=False, width=220)
        self._item_mapping_status = ft.Text("", size=11, color=THEME.text_muted)
        buttons = ft.Row([
            btn_primary("添加/更新", width=110, height=34, on_click=self._add_item_mapping),
            btn_ghost("导入 JSON", width=110, height=34, on_click=self._import_item_mapping_json),
            btn_ghost("导入 JAR", width=110, height=34, on_click=self._import_item_mapping_jar),
            btn_ghost("导出 JSON", width=110, height=34, on_click=self._export_item_mapping_json),
        ], spacing=8)
        s.controls.append(ft.Container(
            content=ft.Column([
                ft.Row([self._item_id_field, self._item_name_field], spacing=10),
                buttons,
                self._item_mapping_status,
            ], spacing=8),
            padding=ft.Padding(left=20, right=20, bottom=18),
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

    def _on_theme_change(self, theme: str) -> None:
        """切换主题"""
        self.app.config._config["ui_settings"]["theme"] = theme
        if theme == "light":
            self.app.page.theme_mode = ft.ThemeMode.LIGHT
        else:
            self.app.page.theme_mode = ft.ThemeMode.DARK
        self.app.page.update()

    def _on_language_change(self, lang: str) -> None:
        """切换语言"""
        self.app.config.language = lang
        self.app.i18n.set_language(lang)
        self.app.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t("messages.ui_text_updated", "UI文本已更新为: {lang}", lang=lang),
        )

    def _on_api_timeout_change(self, e: ft.ControlEvent) -> None:
        """API超时变更"""
        try:
            val = int(e.control.value or "10")
            self.app.config._config["api_timeout"] = max(1, min(60, val))
        except ValueError:
            pass

    def _add_item_mapping(self, e: ft.ControlEvent) -> None:
        try:
            from app.services.item_service import get_item_service
            item_id = (self._item_id_field.value or "").strip()
            name = (self._item_name_field.value or "").strip()
            if ":" not in item_id or not name:
                self._item_mapping_status.value = "请输入形如 modid:item_name 的 ID 和显示名称。"
                self._item_mapping_status.color = THEME.warning
            else:
                get_item_service().set_item_mapping(item_id, name)
                self._item_mapping_status.value = f"已添加映射: {item_id} -> {name}"
                self._item_mapping_status.color = THEME.mc_grass
            self._item_mapping_status.update()
        except Exception as ex:
            self.app.handle_exception(ex, title="添加物品映射失败")

    def _import_item_mapping_json(self, e: ft.ControlEvent) -> None:
        try:
            path = self.app.pick_file(title="导入物品映射 JSON", file_types=[("JSON 文件 (*.json)", "*.json")])
            if not path:
                return
            from app.services.item_service import get_item_service
            count = get_item_service().load_custom_mapping_file(Path(path))
            self._item_mapping_status.value = f"已导入 {count} 条映射。"
            self._item_mapping_status.color = THEME.mc_grass if count else THEME.warning
            self._item_mapping_status.update()
        except Exception as ex:
            self.app.handle_exception(ex, title="导入物品映射失败")

    def _import_item_mapping_jar(self, e: ft.ControlEvent) -> None:
        try:
            path = self.app.pick_file(title="选择模组 JAR", file_types=[("JAR 文件 (*.jar)", "*.jar")])
            if not path:
                return
            from app.services.item_service import get_item_service
            count = get_item_service().extract_language_from_jar(Path(path))
            self._item_mapping_status.value = f"已从 JAR 提取 {count} 条语言映射。"
            self._item_mapping_status.color = THEME.mc_grass if count else THEME.warning
            self._item_mapping_status.update()
        except Exception as ex:
            self.app.handle_exception(ex, title="导入 JAR 语言文件失败")

    def _export_item_mapping_json(self, e: ft.ControlEvent) -> None:
        try:
            path = self.app.save_file(title="导出物品映射 JSON", default_ext=".json", file_types=[("JSON 文件 (*.json)", "*.json")])
            if not path:
                return
            from app.services.item_service import get_item_service
            get_item_service().save_custom_mapping_file(Path(path))
            self._item_mapping_status.value = f"已导出到: {path}"
            self._item_mapping_status.color = THEME.mc_grass
            self._item_mapping_status.update()
        except Exception as ex:
            self.app.handle_exception(ex, title="导出物品映射失败")

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
        c._config["ui_settings"]["theme"] = self._theme_dropdown.value
        c._config["ui_settings"]["language"] = self._lang_dropdown.value
        c._config["batch_processing"]["max_concurrent"] = int(self._max_concurrent_field.value or "2")
        try:
            c._config["api_timeout"] = int(self._api_timeout_field.value or "10")
        except ValueError:
            pass
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

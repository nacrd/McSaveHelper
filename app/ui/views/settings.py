"""Settings View —— 应用配置界面"""
import flet as ft
from typing import TYPE_CHECKING

from app.ui.theme import THEME
from app.ui.components.buttons import btn_ghost
from app.ui.components.fields import text_field, checkbox, label
from app.ui.components.cards import card, section_title

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
            on_change=lambda e: self._on_version_detection_change(e.control.value),
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
            on_change=lambda e: self._on_auto_clear_change(e.control.value),
        )
        s.controls.append(ft.Container(content=self._auto_clear_var,
                                       padding=ft.Padding(left=20, right=20, bottom=10)))

        self._show_log_panel_var = checkbox(
            self._t("settings.ui.show_log_panel", "显示悬浮日志面板"),
            value=cfg.ui_settings.get("show_log_panel", True),
            on_change=lambda e: self._on_show_log_panel_change(e.control.value),
        )
        s.controls.append(ft.Container(content=self._show_log_panel_var,
                                       padding=ft.Padding(left=20, right=20, bottom=10)))

        self._perf_monitor_var = checkbox(
            self._t("settings.ui.enable_performance_monitor", "启用性能监控"),
            value=cfg.ui_settings.get("enable_performance_monitor", False),
            on_change=lambda e: self._on_perf_monitor_change(e.control.value),
        )
        s.controls.append(ft.Container(content=self._perf_monitor_var,
                                       padding=ft.Padding(left=20, right=20, bottom=10)))

        self._perf_print_interval_field = text_field(
            value=str(cfg.ui_settings.get("performance_print_interval", 60)),
            width=100, expand=False,
            on_change=lambda e: self._on_perf_interval_change(e),
        )
        s.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.performance_print_interval", "性能日志打印间隔 (秒)")),
                self._perf_print_interval_field,
            ], spacing=4),
            padding=ft.Padding(left=20, right=20, bottom=20, top=0),
        ))

        c = card(ft.Column(spacing=0), padding=0)
        c.content = s
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=16)))

    # ─── 批量处理 ───────────────────────────────

    def _build_batch_card(self) -> None:
        cfg = self.app.config
        s = ft.Column(spacing=0)
        s.controls.append(section_title(self._t("settings.batch.title", "批量处理")))

        self._max_concurrent_field = text_field(value=str(cfg.max_concurrent), width=100, expand=False,
                                                on_change=lambda e: self._on_max_concurrent_change(e))
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
            on_change=lambda e: self._on_preserve_structure_change(e.control.value),
        )
        s.controls.append(ft.Container(content=self._preserve_var,
                                       padding=ft.Padding(left=20, right=20, bottom=20)))

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
            on_blur=lambda e: self._on_cleanup_blur(),
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
            ft.Button(
                content=self._t("settings.actions.reset", "↻ 重置为默认"),
                width=140, height=38,
                style=ft.ButtonStyle(
                    color=THEME.text_primary, bgcolor=THEME.warning,
                    shape=ft.RoundedRectangleBorder(radius=6),
                ),
                on_click=lambda e: self._reset(),
            ),
        ], spacing=10)
        c = card(ft.Column(spacing=0), padding=0)
        c.content = ft.Container(content=btn_row, padding=20)
        self.controls.append(ft.Container(content=c, padding=ft.Padding(bottom=24)))

    # ─── 回调（即时生效 + 自动保存）──────────────

    def _persist(self) -> None:
        """持久化当前配置到磁盘"""
        c = self.app.config
        c._config["version_detection"] = self._version_var.value
        c._config["ui_settings"]["auto_clear_log"] = self._auto_clear_var.value
        c._config["ui_settings"]["show_log_panel"] = self._show_log_panel_var.value
        c._config["ui_settings"]["enable_performance_monitor"] = self._perf_monitor_var.value
        try:
            c._config["ui_settings"]["performance_print_interval"] = max(5, int(self._perf_print_interval_field.value or "60"))
        except ValueError:
            c._config["ui_settings"]["performance_print_interval"] = 60
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

    def _on_version_detection_change(self, value: bool) -> None:
        self.app.config.migration.version_detection = value
        self._persist()

    def _on_theme_change(self, theme: str) -> None:
        self.app.config._config["ui_settings"]["theme"] = theme
        self.app.page.theme_mode = ft.ThemeMode.LIGHT if theme == "light" else ft.ThemeMode.DARK
        self._persist()
        self.app.page.update()

    def _on_language_change(self, lang: str) -> None:
        self.app.config.language = lang
        self.app.i18n.set_language(lang)
        self._persist()

    def _on_api_timeout_change(self, e: ft.ControlEvent) -> None:
        try:
            val = int(e.control.value or "10")
            self.app.config._config["api_timeout"] = max(1, min(60, val))
        except ValueError:
            return
        self._persist()

    def _on_auto_clear_change(self, value: bool) -> None:
        self._persist()

    def _on_show_log_panel_change(self, value: bool) -> None:
        if hasattr(self.app, 'floating_log_panel') and hasattr(self.app, '_log_fab'):
            self.app._log_fab.set_visible(value)
            self.app.floating_log_panel.set_visible(False)
        self._persist()

    def _on_perf_monitor_change(self, value: bool) -> None:
        from app.ui.performance import perf_monitor, resource_monitor, health_monitor
        if value:
            perf_monitor.enable()
            resource_monitor.start()
            try:
                interval = max(5.0, float(self._perf_print_interval_field.value or "60"))
            except ValueError:
                interval = 60.0
            resource_monitor.set_print_interval(interval)
            health_monitor.set_alert_callback(self.app._on_health_alert)
            self.app._start_heartbeat()
        else:
            perf_monitor.disable()
            resource_monitor.stop()
            self.app._heartbeat_active = False
        self._persist()

    def _on_perf_interval_change(self, e: ft.ControlEvent) -> None:
        from app.ui.performance import resource_monitor
        try:
            interval = max(5.0, float(e.control.value or "60"))
        except ValueError:
            return
        resource_monitor.set_print_interval(interval)
        self._persist()

    def _on_max_concurrent_change(self, e: ft.ControlEvent) -> None:
        try:
            int(e.control.value or "2")
        except ValueError:
            return
        self._persist()

    def _on_preserve_structure_change(self, value: bool) -> None:
        self._persist()

    def _on_cleanup_blur(self) -> None:
        self._persist()

    def _restore_default_cleanup(self) -> None:
        self._cleanup_field.value = "\n".join(["*.log", "cache/", "logs/"])
        self._cleanup_field.update()
        self._persist()

    def _reset(self) -> None:
        self.app.config.reset_config()
        self.app.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t("settings.messages.reset_success", "已恢复默认设置"),
        )
        self._build()

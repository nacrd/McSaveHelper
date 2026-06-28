"""Settings View —— 应用配置界面

每个设置分区支持点击标题栏展开/收起，减少纵向占用。
"""
import flet as ft
from typing import TYPE_CHECKING, List

from app.ui.theme import THEME, mc_border
from app.ui.icons import IconSet
from app.ui.components.buttons import btn_ghost
from app.ui.components.fields import text_field, checkbox, label, dropdown
from app.ui.components.cards import card
from app.ui.components.layout import page_header

if TYPE_CHECKING:
    from app.application import Application


def _collapsible_section(
    title: str,
    content: ft.Control,
    expanded: bool = False,
) -> ft.Container:
    """Wrap a section content in a collapsible card.

    点击标题栏切换展开/收起；收起时仅显示标题行，节省纵向空间。

    Args:
        title: Section title text
        content: Section body (a ft.Column or any control)
        expanded: Initial state

    Returns:
        ft.Container: Complete collapsible card
    """
    # Arrow indicator
    arrow = ft.Icon(
        ft.Icons.KEYBOARD_ARROW_DOWN if expanded else ft.Icons.KEYBOARD_ARROW_RIGHT,
        size=18,
        color=THEME.text_secondary,
    )

    # Title bar row
    title_row = ft.Row(
        [
            ft.Container(
                content=ft.Text("▣", size=13, color=THEME.text_primary),
                width=24, height=24,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.mc_grass,
                border_radius=4,
                border=mc_border(1),
            ),
            ft.Text(
                title,
                size=14,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
                font_family="monospace",
                expand=True,
            ),
            arrow,
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    title_bar = ft.Container(
        content=title_row,
        padding=ft.Padding(left=16, right=16, top=12, bottom=12),
        ink=True,
        border_radius=6,
    )

    # Content wrapper — hidden when collapsed
    body_wrapper = ft.Container(
        content=content,
        padding=ft.Padding(left=4, right=4, top=0, bottom=4),
        animate_opacity=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        animate_size=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    # Track expanded state on the body container
    body_wrapper.visible = expanded
    body_wrapper.opacity = 1.0 if expanded else 0.0

    def _toggle(e: ft.ControlEvent = None) -> None:
        is_visible = body_wrapper.visible
        body_wrapper.visible = not is_visible
        body_wrapper.opacity = 0.0 if is_visible else 1.0
        arrow.name = (
            ft.Icons.KEYBOARD_ARROW_DOWN if not is_visible
            else ft.Icons.KEYBOARD_ARROW_RIGHT
        )
        body_wrapper.update()
        arrow.update()

    title_bar.on_click = _toggle

    card_container = ft.Container(
        content=ft.Column(
            [title_bar, body_wrapper],
            spacing=0,
        ),
        bgcolor=THEME.bg_card,
        border=mc_border(),
        border_radius=8,
    )

    return ft.Container(
        content=card_container,
        padding=ft.Padding(bottom=12),
    )


class SettingsView(ft.Column):
    """配置设置视图（可折叠分区）"""

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
        self.controls.append(page_header(
            "设置",
            ft.Text("管理通用选项、界面偏好、批量处理和清理规则", size=12, color=THEME.text_muted),
            icon=IconSet.SETTINGS,
        ))
        self._build_general_card()
        self._build_ui_card()
        self._build_batch_card()
        self._build_cleanup_card()
        self._build_action_card()

    # ─── 通用设置 ───────────────────────────────

    def _build_general_card(self) -> None:
        cfg = self.app.config
        body = ft.Column(spacing=0)

        self._version_var = checkbox(
            self._t("settings.general.version_detection", "启用版本自动检测"),
            value=cfg.version_detection,
            on_change=lambda e: self._on_version_detection_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=self._version_var,
            padding=ft.Padding(left=16, right=16, top=10),
        ))

        self._api_timeout_field = text_field(
            value=str(cfg.api_timeout),
            width=100, expand=False,
            on_change=lambda e: self._on_api_timeout_change(e),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.general.api_timeout", "API 超时 (秒)")),
                self._api_timeout_field,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=16, top=10),
        ))

        self.controls.append(_collapsible_section(
            self._t("settings.general.title", "通用设置"),
            body,
            expanded=True,  # 默认展开
        ))

    # ─── 界面设置 ───────────────────────────────

    def _build_ui_card(self) -> None:
        cfg = self.app.config
        body = ft.Column(spacing=0)

        self._theme_dropdown = dropdown(
            options=[
                ft.dropdown.Option("dark", "暗色"),
                ft.dropdown.Option("light", "浅色"),
            ],
            value=cfg.theme,
            width=120,
            on_change=lambda e: self._on_theme_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.theme", "主题")),
                self._theme_dropdown,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=8, top=10),
        ))

        self._lang_dropdown = dropdown(
            options=[
                ft.dropdown.Option("zh_CN", "简体中文"),
                ft.dropdown.Option("en_US", "English"),
            ],
            value=cfg.language,
            width=120,
            on_change=lambda e: self._on_language_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.language", "语言")),
                self._lang_dropdown,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._sidebar_mode_dropdown = dropdown(
            options=[
                ft.dropdown.Option("expanded", "展开"),
                ft.dropdown.Option("collapsed", "收窄"),
                ft.dropdown.Option("auto", "自动"),
            ],
            value=cfg.ui_settings.get("sidebar_mode", "auto"),
            width=120,
            on_change=lambda e: self._on_sidebar_mode_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.sidebar_mode", "侧边栏模式")),
                self._sidebar_mode_dropdown,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._auto_clear_var = checkbox(
            self._t("settings.ui.auto_clear_log", "自动清除旧日志"),
            value=cfg.ui_settings.get("auto_clear_log", False),
            on_change=lambda e: self._on_auto_clear_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=self._auto_clear_var,
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._show_log_panel_var = checkbox(
            self._t("settings.ui.show_log_panel", "显示悬浮日志面板"),
            value=cfg.ui_settings.get("show_log_panel", True),
            on_change=lambda e: self._on_show_log_panel_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=self._show_log_panel_var,
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._perf_monitor_var = checkbox(
            self._t("settings.ui.enable_performance_monitor", "启用性能监控"),
            value=cfg.ui_settings.get("enable_performance_monitor", False),
            on_change=lambda e: self._on_perf_monitor_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=self._perf_monitor_var,
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._perf_print_interval_field = text_field(
            value=str(cfg.ui_settings.get("performance_print_interval", 60)),
            width=100, expand=False,
            on_change=lambda e: self._on_perf_interval_change(e),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.performance_print_interval", "性能日志打印间隔 (秒)")),
                self._perf_print_interval_field,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=16, top=0),
        ))

        self.controls.append(_collapsible_section(
            self._t("settings.ui.title", "界面设置"),
            body,
            expanded=True,
        ))

    # ─── 批量处理 ───────────────────────────────

    def _build_batch_card(self) -> None:
        cfg = self.app.config
        body = ft.Column(spacing=0)

        self._max_concurrent_field = text_field(
            value=str(cfg.max_concurrent),
            width=100, expand=False,
            on_change=lambda e: self._on_max_concurrent_change(e),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.batch.max_concurrent", "最大并发处理数 (1‑16)")),
                self._max_concurrent_field,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=8, top=10),
        ))

        self._preserve_var = checkbox(
            self._t("settings.batch.preserve_structure", "保留原始文件结构"),
            value=cfg.batch_processing.get("preserve_structure", True),
            on_change=lambda e: self._on_preserve_structure_change(e.control.value),
        )
        body.controls.append(ft.Container(
            content=self._preserve_var,
            padding=ft.Padding(left=16, right=16, bottom=16),
        ))

        self.controls.append(_collapsible_section(
            self._t("settings.batch.title", "批量处理"),
            body,
            expanded=False,  # 默认收起
        ))

    # ─── 清理模式 ───────────────────────────────

    def _build_cleanup_card(self) -> None:
        cfg = self.app.config
        body = ft.Column(spacing=0)

        body.controls.append(ft.Container(
            content=ft.Text(
                self._t("settings.cleanup.description",
                        "转换完成后自动删除的文件/目录模式（每行一个，支持通配符）"),
                size=12, color=THEME.text_muted,
            ),
            padding=ft.Padding(left=16, right=16, bottom=8, top=10),
        ))

        patterns = cfg.cleanup_patterns
        self._cleanup_field = ft.TextField(
            value="\n".join(patterns) if isinstance(patterns, list) else "",
            multiline=True, min_lines=3, max_lines=6,
            border_color=THEME.border_standard, text_size=13,
            bgcolor=THEME.bg_secondary, border_radius=6,
            on_blur=lambda e: self._on_cleanup_blur(),
        )
        body.controls.append(ft.Container(
            content=self._cleanup_field,
            padding=ft.Padding(left=16, right=16),
        ))

        body.controls.append(ft.Container(
            content=btn_ghost(
                self._t("settings.cleanup.restore_defaults", "恢复默认"),
                width=120, height=32,
                on_click=lambda e: self._restore_default_cleanup(),
            ),
            padding=ft.Padding(left=16, right=16, bottom=16, top=8),
        ))

        self.controls.append(_collapsible_section(
            self._t("settings.cleanup.title", "清理模式"),
            body,
            expanded=False,
        ))

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
        c.content = ft.Container(content=btn_row, padding=16)
        self.controls.append(
            ft.Container(content=c, padding=ft.Padding(bottom=24)))

    # ─── 回调（即时生效 + 自动保存）──────────────

    def _persist(self) -> None:
        """持久化当前配置到磁盘"""
        c = self.app.config
        c._config["version_detection"] = self._version_var.value
        c._config["ui_settings"]["auto_clear_log"] = self._auto_clear_var.value
        c._config["ui_settings"]["show_log_panel"] = self._show_log_panel_var.value
        c._config["ui_settings"]["enable_performance_monitor"] = self._perf_monitor_var.value
        try:
            c._config["ui_settings"]["performance_print_interval"] = max(
                5, int(self._perf_print_interval_field.value or "60"))
        except ValueError:
            c._config["ui_settings"]["performance_print_interval"] = 60
        c._config["ui_settings"]["preserve_structure"] = self._preserve_var.value
        c._config["ui_settings"]["theme"] = self._theme_dropdown.value
        c._config["ui_settings"]["language"] = self._lang_dropdown.value
        c._config["batch_processing"]["max_concurrent"] = int(
            self._max_concurrent_field.value or "2")
        try:
            c._config["api_timeout"] = int(self._api_timeout_field.value or "10")
        except ValueError:
            pass
        c.cleanup_patterns = [
            x.strip() for x in self._cleanup_field.value.split("\n") if x.strip()]
        c.save()

    def _on_version_detection_change(self, value: bool) -> None:
        self.app.config.migration.version_detection = value
        self._persist()

    def _on_theme_change(self, theme: str) -> None:
        from app.ui.theme import get_theme_manager
        self.app.config._config["ui_settings"]["theme"] = theme
        get_theme_manager().set_mode(theme)
        self._persist()
        try:
            self.app.page.bgcolor = THEME.bg_primary
            self.app.page.window.bgcolor = THEME.bg_primary
            self.app.page.theme_mode = (
                ft.ThemeMode.LIGHT if theme == "light" else ft.ThemeMode.DARK
            )
            self.app.page.update()
        except Exception:
            pass

    def _on_sidebar_mode_change(self, mode: str) -> None:
        self.app.config._config["ui_settings"]["sidebar_mode"] = mode
        self._persist()
        try:
            if hasattr(self.app, '_sidebar'):
                if mode == "collapsed":
                    self.app._sidebar.set_collapsed(True)
                elif mode == "expanded":
                    self.app._sidebar.set_collapsed(False)
        except Exception:
            pass

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

"""Settings View —— 应用配置界面

每个设置分区支持点击标题栏展开/收起，减少纵向占用。
"""
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

import flet as ft

from app.controllers.settings_io_controller import (
    CacheClearOutcome,
    SettingsCacheSnapshot,
    SettingsIOController,
    SettingsIOControllerDependencies,
)
from app.models.config import ApplicationSettings
from app.models.responsive_layout import ResponsiveLayout
from app.presenters.runtime_observability import (
    format_cache_registry_report,
    format_runtime_snapshot,
)
from app.services.cache_registry import CacheRegistryStats
from app.services.execution_runtime import (
    ExecutionRuntime,
    ExecutionRuntimeSnapshot,
)
from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.components.buttons import btn_ghost
from app.ui.components.fields import text_field, checkbox, label, dropdown
from app.ui.components.cards import card
from app.ui.components.layout import page_header
from app.ui.views.settings_sections import collapsible_section as _collapsible_section
from app.ui.utils import format_size, run_on_ui, safe_update


Translate = Callable[..., str]
DialogCallback = Callable[[str, str], None]
CacheSnapshot = Callable[[], CacheRegistryStats]
CacheClear = Callable[[], Mapping[str, int]]


@dataclass(frozen=True)
class SettingsViewDependencies:
    """设置页与应用壳层之间的显式端口。"""

    load_settings: Callable[[], ApplicationSettings]
    save_settings: Callable[[ApplicationSettings], None]
    reset_settings: Callable[[], ApplicationSettings]
    translate: Translate
    apply_theme: Callable[[str], None]
    apply_language: Callable[[str], None]
    set_sidebar_mode: Callable[[str], None]
    set_log_panel_visible: Callable[[bool], None]
    configure_performance_monitor: Callable[[bool, float], None]
    set_performance_interval: Callable[[float], None]
    info_dialog: DialogCallback
    error_dialog: DialogCallback
    pick_directory: Callable[[], Optional[str]]
    cache_snapshot: CacheSnapshot
    clear_caches: CacheClear
    cache_path: Callable[[], str]
    execution_runtime: ExecutionRuntime
    runtime_snapshot: Callable[[], Optional[ExecutionRuntimeSnapshot]]
    save_debounce_seconds: float = 0.35


class SettingsView(ft.Column):
    """配置设置视图（可折叠分区）"""

    def __init__(self, dependencies: SettingsViewDependencies) -> None:
        """通过显式依赖端口构建设置页。

        Args:
            dependencies: 设置读写、主题/语言应用与对话框等壳层端口。
        """
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._deps = dependencies
        self._disposed = False
        self._operation_busy = False
        self._io_controller = SettingsIOController(
            SettingsIOControllerDependencies(
                execution_runtime=dependencies.execution_runtime,
                save_settings=dependencies.save_settings,
                reset_settings=dependencies.reset_settings,
                cache_snapshot=dependencies.cache_snapshot,
                clear_caches=dependencies.clear_caches,
                cache_path=dependencies.cache_path,
                runtime_snapshot=dependencies.runtime_snapshot,
                dispatch=self._dispatch_result,
                save_debounce_seconds=dependencies.save_debounce_seconds,
            )
        )
        self._build()

    @property
    def _t(self) -> Translate:
        return self._deps.translate

    def _settings(self) -> ApplicationSettings:
        return self._deps.load_settings()

    def _build(self) -> None:
        self.controls.clear()
        self._save_status_icon = ft.Icon(
            IconSet.INFO,
            size=16,
            color=THEME.text_muted,
        )
        self._save_status_text = ft.Text(
            self._t("settings.save_status.auto", "更改会自动保存"),
            size=12,
            color=THEME.text_muted,
        )
        save_status = ft.Row(
            [self._save_status_icon, self._save_status_text],
            spacing=5,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._page_header = page_header(
            "设置",
            ft.Text("管理通用选项、界面偏好、批量处理和清理规则", size=12, color=THEME.text_muted),
            icon=IconSet.SETTINGS,
            status=save_status,
        )
        self._sections: list[ft.Control] = []
        self._build_general_card()
        self._build_ui_card()
        self._build_cache_card()
        self._build_batch_card()
        self._build_cleanup_card()
        self._build_action_card()
        self._settings_left = ft.Column(
            [self._sections[index] for index in (0, 2, 3)],
            spacing=0,
            expand=True,
        )
        self._settings_right = ft.Column(
            [self._sections[index] for index in (1, 4, 5)],
            spacing=0,
            expand=True,
        )
        self._settings_host = ft.Container()
        self.controls = [self._page_header, self._settings_host]
        self.set_compact_mode(False)

    def set_compact_mode(self, compact: bool) -> None:
        """Use one column in constrained windows and two on desktop."""
        host = getattr(self, "_settings_host", None)
        if host is None:
            return
        if compact:
            host.content = ft.Column(
                list(self._sections),
                spacing=0,
            )
        else:
            host.content = ft.Row(
                [self._settings_left, self._settings_right],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        safe_update(host)

    def set_responsive_layout(self, layout: ResponsiveLayout) -> None:
        """Choose columns from the real content width left by the sidebar.

        The standard shell still leaves too little horizontal space for two
        settings cards with form controls.  Reserve the two-column layout for
        roomy windows so fields and helper text never extend past the viewport.

        Args:
            layout: Current shell layout resolved from the viewport.
        """
        self.set_compact_mode(layout.density != "roomy")

    # ─── 通用设置 ───────────────────────────────

    def _build_general_card(self) -> None:
        cfg = self._settings()
        body = ft.Column(spacing=0)

        self._version_var = checkbox(
            self._t("settings.general.version_detection", "启用版本自动检测"),
            value=cfg.version_detection,
            on_change=lambda _: self._on_version_detection_change(
                bool(self._version_var.value)
            ),
        )
        body.controls.append(ft.Container(
            content=self._version_var,
            padding=ft.Padding(left=16, right=16, top=10),
        ))

        self._api_timeout_field = text_field(
            value=str(cfg.api_timeout),
            width=100, expand=False,
            on_change=lambda _: self._on_api_timeout_change(),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.general.api_timeout", "API 超时 (秒)")),
                self._api_timeout_field,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=16, top=10),
        ))

        self._sections.append(_collapsible_section(
            self._t("settings.general.title", "通用设置"),
            body,
            expanded=True,  # 默认展开
        ))

    # ─── 界面设置 ───────────────────────────────

    def _build_ui_card(self) -> None:
        cfg = self._settings()
        body = ft.Column(spacing=0)
        body.controls.append(self._build_theme_row(cfg))
        body.controls.append(self._build_language_row(cfg))
        body.controls.append(self._build_sidebar_mode_row(cfg))
        body.controls.append(self._build_minecraft_dir_row(cfg))
        body.controls.append(self._build_auto_import_lang_row(cfg))
        body.controls.append(self._build_auto_clear_log_row(cfg))
        body.controls.append(self._build_show_log_panel_row(cfg))
        body.controls.append(self._build_perf_monitor_row(cfg))
        body.controls.append(self._build_perf_interval_row(cfg))
        self._sections.append(_collapsible_section(
            self._t("settings.ui.title", "界面设置"),
            body,
            expanded=True,
        ))

    def _settings_field_pad(
        self,
        content: ft.Control,
        *,
        top: int = 0,
        bottom: int = 8,
    ) -> ft.Container:
        return ft.Container(
            content=content,
            padding=ft.Padding(left=16, right=16, bottom=bottom, top=top),
        )

    def _build_theme_row(self, cfg: Any) -> ft.Container:
        self._theme_dropdown = dropdown(
            options=[
                ft.dropdown.Option("dark", "暗色"),
                ft.dropdown.Option("light", "浅色"),
            ],
            value=cfg.theme,
            width=120,
            on_change=lambda _: self._on_theme_change(
                self._theme_dropdown.value or "dark"
            ),
        )
        return self._settings_field_pad(
            ft.Column([
                label(self._t("settings.ui.theme", "主题")),
                self._theme_dropdown,
            ], spacing=4),
            top=10,
        )

    def _build_language_row(self, cfg: Any) -> ft.Container:
        self._lang_dropdown = dropdown(
            options=[
                ft.dropdown.Option("zh_CN", "简体中文"),
                ft.dropdown.Option("en_US", "English"),
            ],
            value=cfg.language,
            width=120,
            on_change=lambda _: self._on_language_change(
                self._lang_dropdown.value or "zh_CN"
            ),
        )
        return self._settings_field_pad(
            ft.Column([
                label(self._t("settings.ui.language", "语言")),
                self._lang_dropdown,
            ], spacing=4),
        )

    def _build_sidebar_mode_row(self, cfg: Any) -> ft.Container:
        self._sidebar_mode_dropdown = dropdown(
            options=[
                ft.dropdown.Option("expanded", "展开"),
                ft.dropdown.Option("collapsed", "收窄"),
                ft.dropdown.Option("auto", "自动"),
            ],
            value=cfg.sidebar_mode,
            width=120,
            on_change=lambda _: self._on_sidebar_mode_change(
                self._sidebar_mode_dropdown.value or "auto"
            ),
        )
        return self._settings_field_pad(
            ft.Column([
                label(self._t("settings.ui.sidebar_mode", "侧边栏模式")),
                self._sidebar_mode_dropdown,
            ], spacing=4),
        )

    def _build_minecraft_dir_row(self, cfg: Any) -> ft.Container:
        self._minecraft_dir_field = text_field(
            value=cfg.minecraft_dir,
            hint_text=self._t(
                "settings.ui.minecraft_dir_hint",
                r"例如 F:\Game\minecraft\.minecraft（可留空自动推断）",
            ),
            expand=True,
            on_change=lambda _: self._on_minecraft_dir_change(),
        )
        return self._settings_field_pad(
            ft.Column([
                label(self._t("settings.ui.minecraft_dir", "Minecraft 目录")),
                ft.Row(
                    [
                        self._minecraft_dir_field,
                        btn_ghost(
                            self._t("settings.ui.browse", "浏览"),
                            height=44,
                            on_click=self._browse_minecraft_dir,
                        ),
                    ],
                    spacing=8,
                ),
                ft.Text(
                    self._t(
                        "settings.ui.minecraft_dir_help",
                        "用于导入语言/贴图。优先此路径；留空则从当前存档向上查找 "
                        ".minecraft，或使用系统默认目录。",
                    ),
                    size=11,
                    color=THEME.text_muted,
                ),
            ], spacing=4),
        )

    def _build_auto_import_lang_row(self, cfg: Any) -> ft.Container:
        self._auto_import_mc_lang_var = checkbox(
            self._t(
                "settings.ui.auto_import_mc_lang",
                "设置存档后自动导入 Minecraft 语言",
            ),
            value=cfg.auto_import_mc_lang,
            on_change=lambda _: self._on_auto_import_mc_lang_change(
                bool(self._auto_import_mc_lang_var.value)
            ),
        )
        return self._settings_field_pad(
            ft.Column([
                self._auto_import_mc_lang_var,
                ft.Text(
                    self._t(
                        "settings.ui.auto_import_mc_lang_help",
                        "选择当前存档后，后台按 UI 语言自动导入原版物品/方块名称。",
                    ),
                    size=11,
                    color=THEME.text_muted,
                ),
            ], spacing=2),
        )

    def _build_auto_clear_log_row(self, cfg: Any) -> ft.Container:
        self._auto_clear_var = checkbox(
            self._t("settings.ui.auto_clear_log", "自动清除旧日志"),
            value=cfg.auto_clear_log,
            on_change=lambda _: self._on_auto_clear_change(
                bool(self._auto_clear_var.value)
            ),
        )
        return self._settings_field_pad(self._auto_clear_var)

    def _build_show_log_panel_row(self, cfg: Any) -> ft.Container:
        self._show_log_panel_var = checkbox(
            self._t("settings.ui.show_log_panel", "显示悬浮日志面板"),
            value=cfg.show_log_panel,
            on_change=lambda _: self._on_show_log_panel_change(
                bool(self._show_log_panel_var.value)
            ),
        )
        return self._settings_field_pad(self._show_log_panel_var)

    def _build_perf_monitor_row(self, cfg: Any) -> ft.Container:
        self._perf_monitor_var = checkbox(
            self._t("settings.ui.enable_performance_monitor", "启用性能监控"),
            value=cfg.enable_performance_monitor,
            on_change=lambda _: self._on_perf_monitor_change(
                bool(self._perf_monitor_var.value)
            ),
        )
        return self._settings_field_pad(self._perf_monitor_var)

    def _build_perf_interval_row(self, cfg: Any) -> ft.Container:
        self._perf_print_interval_field = text_field(
            value=str(cfg.performance_print_interval),
            width=100,
            expand=False,
            on_change=lambda _: self._on_perf_interval_change(),
        )
        return self._settings_field_pad(
            ft.Column([
                label(self._t(
                    "settings.ui.performance_print_interval",
                    "性能日志打印间隔 (秒)",
                )),
                self._perf_print_interval_field,
            ], spacing=4),
            bottom=16,
        )

    # ─── 地图缓存 ───────────────────────────────

    def _build_cache_card(self) -> None:
        body = ft.Column(spacing=0)
        body.controls.append(self._cache_description())
        body.controls.append(self._cache_summary_block())
        body.controls.append(self._cache_action_row())
        self._sections.append(_collapsible_section(
            self._t("settings.cache.title", "应用缓存"),
            body,
            expanded=True,
        ))

    def _cache_description(self) -> ft.Container:
        return ft.Container(
            content=ft.Text(
                self._t(
                    "settings.cache.description",
                    "统一管理世界索引、纹理和地图渲染缓存；内存受总预算约束，"
                    "地图瓦片仍持久化到本地以加快再次打开。",
                ),
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=16, right=16, bottom=8, top=10),
        )

    def _cache_summary_block(self) -> ft.Container:
        self._cache_summary = ft.Text(
            self._t("settings.cache.loading", "正在读取缓存信息…"),
            size=12,
            color=THEME.text_primary,
            font_family="monospace",
            selectable=True,
        )
        self._runtime_summary = ft.Text(
            self._t("settings.cache.runtime_loading", "正在读取后台运行时…"),
            size=12,
            color=THEME.text_primary,
            font_family="monospace",
            selectable=True,
        )
        self._cache_path_label = ft.Text(
            self._t("settings.cache.path_loading", "地图瓦片路径: —"),
            size=11,
            color=THEME.text_muted,
            selectable=True,
        )
        return ft.Container(
            content=ft.Column([
                self._cache_summary,
                self._runtime_summary,
                self._cache_path_label,
            ], spacing=8),
            padding=ft.Padding(left=16, right=16, bottom=10),
        )

    def _cache_action_row(self) -> ft.Container:
        self._cache_refresh_button = btn_ghost(
            self._t("settings.cache.refresh", "刷新"),
            width=100,
            height=44,
            on_click=lambda e: self._refresh_cache_stats(show_error=True),
        )
        self._cache_clear_button = btn_ghost(
            self._t("settings.cache.clear", "清理缓存"),
            width=120,
            height=44,
            on_click=lambda e: self._clear_map_cache(),
        )
        return ft.Container(
            content=ft.Row(
                [
                    self._cache_refresh_button,
                    self._cache_clear_button,
                ],
                spacing=10,
            ),
            padding=ft.Padding(left=16, right=16, bottom=16),
        )

    def _refresh_cache_stats(self, *, show_error: bool = False) -> None:
        if self._disposed:
            return
        self._set_cache_busy(True)
        self._io_controller.refresh_cache(
            self._apply_cache_snapshot,
            lambda error: self._apply_cache_error(error, show_error),
        )

    def _apply_cache_snapshot(self, snapshot: SettingsCacheSnapshot) -> None:
        if self._disposed:
            return
        self._set_cache_busy(False)
        self._cache_summary.value = format_cache_registry_report(
            snapshot.cache,
            format_size=format_size,
        )
        self._runtime_summary.value = (
            format_runtime_snapshot(snapshot.runtime)
            if snapshot.runtime is not None
            else self._t("settings.cache.runtime_unavailable", "后台运行时: 不可用")
        )
        self._cache_path_label.value = self._t(
            "settings.cache.path_value",
            "地图瓦片路径: {path}",
            path=snapshot.cache_path,
        )
        safe_update(self._cache_summary)
        safe_update(self._runtime_summary)
        safe_update(self._cache_path_label)

    def _apply_cache_error(self, error: Exception, show_error: bool) -> None:
        if self._disposed:
            return
        self._set_cache_busy(False)
        self._cache_summary.value = self._t(
            "settings.cache.read_failed",
            "无法读取缓存信息: {error}",
            error=str(error),
        )
        safe_update(self._cache_summary)
        if show_error:
            self._deps.error_dialog(
                self._t("dialogs.error", "错误"),
                str(error),
            )

    def _clear_map_cache(self) -> None:
        if self._disposed:
            return
        self._set_cache_busy(True)
        self._io_controller.clear_cache(
            self._apply_cache_clear_success,
            lambda error: self._apply_cache_error(error, True),
        )

    def _apply_cache_clear_success(self, outcome: CacheClearOutcome) -> None:
        if self._disposed:
            return
        self._apply_cache_snapshot(outcome.snapshot)
        metrics = outcome.metrics
        self._deps.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t(
                "settings.cache.clear_success",
                "已清理地图缓存：{deleted} 个文件（{freed}），内存 chunk {memory} 条",
                deleted=metrics.deleted_files,
                freed=format_size(metrics.freed_bytes),
                memory=metrics.memory_chunks_cleared,
            ),
        )

    def _set_cache_busy(self, busy: bool) -> None:
        self._cache_refresh_button.disabled = busy
        self._cache_clear_button.disabled = busy
        safe_update(self._cache_refresh_button)
        safe_update(self._cache_clear_button)

    # ─── 批量处理 ───────────────────────────────

    def _build_batch_card(self) -> None:
        cfg = self._settings()
        body = ft.Column(spacing=0)

        self._max_concurrent_field = text_field(
            value=str(cfg.max_concurrent),
            width=100, expand=False,
            on_change=lambda _: self._on_max_concurrent_change(),
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
            value=cfg.preserve_structure,
            on_change=lambda _: self._on_preserve_structure_change(
                bool(self._preserve_var.value)
            ),
        )
        body.controls.append(ft.Container(
            content=self._preserve_var,
            padding=ft.Padding(left=16, right=16, bottom=16),
        ))

        self._sections.append(_collapsible_section(
            self._t("settings.batch.title", "批量处理"),
            body,
            expanded=False,  # 默认收起
        ))

    # ─── 清理模式 ───────────────────────────────

    def _build_cleanup_card(self) -> None:
        cfg = self._settings()
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
            value="\n".join(patterns),
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
                width=120, height=44,
                on_click=lambda e: self._restore_default_cleanup(),
            ),
            padding=ft.Padding(left=16, right=16, bottom=16, top=8),
        ))

        self._sections.append(_collapsible_section(
            self._t("settings.cleanup.title", "清理模式"),
            body,
            expanded=False,
        ))

    # ─── 操作按钮 ───────────────────────────────

    def _build_action_card(self) -> None:
        btn_row = ft.Row([
            ft.Button(
                content=self._t("settings.actions.reset", "↻ 重置为默认"),
                width=160, height=44,
                style=ft.ButtonStyle(
                    color=THEME.text_primary, bgcolor=THEME.warning,
                    shape=ft.RoundedRectangleBorder(radius=6),
                ),
                on_click=lambda e: self._reset(),
            ),
        ], spacing=10)
        c = card(ft.Column(spacing=0), padding=0)
        c.content = ft.Container(content=btn_row, padding=16)
        self._sections.append(
            ft.Container(content=c, padding=ft.Padding(bottom=24)))

    # ─── 回调（即时生效 + 自动保存）──────────────

    @staticmethod
    def _bounded_int(
        value: object,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            parsed = int(str(value or default))
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _performance_interval(self) -> int:
        return self._bounded_int(
            self._perf_print_interval_field.value,
            60,
            5,
            86400,
        )

    def _collect_settings(self) -> ApplicationSettings:
        """从控件读取并校验一份完整设置快照。"""
        cleanup_value = self._cleanup_field.value or ""
        return ApplicationSettings(
            version_detection=bool(self._version_var.value),
            api_timeout=self._bounded_int(
                self._api_timeout_field.value,
                10,
                1,
                60,
            ),
            theme=self._theme_dropdown.value or "dark",
            language=self._lang_dropdown.value or "zh_CN",
            sidebar_mode=self._sidebar_mode_dropdown.value or "auto",
            auto_clear_log=bool(self._auto_clear_var.value),
            show_log_panel=bool(self._show_log_panel_var.value),
            enable_performance_monitor=bool(self._perf_monitor_var.value),
            performance_print_interval=self._performance_interval(),
            max_concurrent=self._bounded_int(
                self._max_concurrent_field.value,
                2,
                1,
                16,
            ),
            preserve_structure=bool(self._preserve_var.value),
            cleanup_patterns=tuple(
                item.strip()
                for item in cleanup_value.splitlines()
                if item.strip()
            ),
            minecraft_dir=(self._minecraft_dir_field.value or "").strip(),
            auto_import_mc_lang=bool(self._auto_import_mc_lang_var.value),
        )

    def _persist(self) -> bool:
        """提交最新设置快照，并在防抖窗口内合并连续输入。"""
        if self._disposed or self._operation_busy:
            return False
        try:
            settings = self._collect_settings()
        except Exception as error:
            self._apply_save_error(error)
            return False
        self._set_save_status(
            self._t("settings.save_status.pending", "等待保存"),
            IconSet.INFO,
            THEME.warning,
        )
        self._io_controller.schedule_save(
            settings,
            self._apply_save_success,
            self._apply_save_error,
        )
        return True

    def _apply_save_success(self) -> None:
        if self._disposed:
            return
        self._set_save_status(
            self._t("settings.save_status.saved", "已保存"),
            IconSet.SUCCESS,
            THEME.success,
        )

    def _apply_save_error(self, error: Exception) -> None:
        if self._disposed:
            return
        self._set_save_status(
            self._t("settings.save_status.failed", "保存失败"),
            IconSet.ERROR,
            THEME.error,
        )
        self._deps.error_dialog(
            self._t("dialogs.error", "错误"),
            str(error),
        )

    def _set_save_status(
        self,
        text: str,
        icon: ft.IconData,
        color: str,
    ) -> None:
        """Update the persistent settings feedback in one place."""
        self._save_status_text.value = text
        self._save_status_text.color = color
        self._save_status_icon.icon = icon
        self._save_status_icon.color = color
        safe_update(self._page_header.status_host)

    def _on_version_detection_change(self, value: bool) -> None:
        del value
        self._persist()

    def _on_theme_change(self, theme: str) -> None:
        if self._persist():
            self._deps.apply_theme(theme)

    def _on_sidebar_mode_change(self, mode: str) -> None:
        if self._persist():
            self._deps.set_sidebar_mode(mode)

    def _on_language_change(self, lang: str) -> None:
        if self._persist():
            self._deps.apply_language(lang)

    def _on_minecraft_dir_change(self) -> None:
        self._persist()

    def _on_auto_import_mc_lang_change(self, enabled: bool) -> None:
        """持久化「设置存档后自动导入语言」开关。

        Args:
            enabled: 复选框新值（由控件绑定传入；实际以控件当前状态为准）。
        """
        del enabled
        self._persist()

    def _browse_minecraft_dir(
        self,
        e: Optional[ft.ControlEvent] = None,
    ) -> None:
        del e
        try:
            path = self._deps.pick_directory()
            if not path:
                return
            self._minecraft_dir_field.value = path
            self._persist()
            safe_update(self._minecraft_dir_field)
        except Exception as ex:
            self._deps.error_dialog(
                self._t("settings.ui.minecraft_dir_error", "选择目录失败"),
                str(ex),
            )

    def _on_api_timeout_change(self) -> None:
        try:
            int(self._api_timeout_field.value or "10")
        except ValueError:
            return
        self._persist()

    def _on_auto_clear_change(self, value: bool) -> None:
        self._persist()

    def _on_show_log_panel_change(self, value: bool) -> None:
        if self._persist():
            self._deps.set_log_panel_visible(value)

    def _on_perf_monitor_change(self, value: bool) -> None:
        if self._persist():
            self._deps.configure_performance_monitor(
                value,
                float(self._performance_interval()),
            )

    def _on_perf_interval_change(self) -> None:
        try:
            interval = max(
                5.0,
                float(self._perf_print_interval_field.value or "60"),
            )
        except ValueError:
            return
        if self._persist():
            self._deps.set_performance_interval(interval)

    def _on_max_concurrent_change(self) -> None:
        try:
            int(self._max_concurrent_field.value or "2")
        except ValueError:
            return
        self._persist()

    def _on_preserve_structure_change(self, value: bool) -> None:
        self._persist()

    def _on_cleanup_blur(self) -> None:
        self._persist()

    def _restore_default_cleanup(self) -> None:
        self._cleanup_field.value = "\n".join(["*.log", "cache/", "logs/"])
        safe_update(self._cleanup_field)
        self._persist()

    def _reset(self) -> None:
        if self._disposed or self._operation_busy:
            return
        self._set_operation_busy(True)
        self._set_save_status(
            self._t("settings.save_status.resetting", "正在重置"),
            IconSet.INFO,
            THEME.warning,
        )
        self._io_controller.reset(
            self._apply_reset_success,
            self._apply_reset_error,
        )

    def _apply_reset_success(self, settings: ApplicationSettings) -> None:
        if self._disposed:
            return
        self._operation_busy = False
        self.disabled = False
        self._apply_settings_effects(settings)
        self._build()
        self._set_save_status(
            self._t("settings.save_status.saved", "已保存"),
            IconSet.SUCCESS,
            THEME.success,
        )
        safe_update(self)
        self._refresh_cache_stats()
        self._deps.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t("settings.messages.reset_success", "已恢复默认设置"),
        )

    def _apply_reset_error(self, error: Exception) -> None:
        if self._disposed:
            return
        self._set_operation_busy(False)
        self._apply_save_error(error)

    def _apply_settings_effects(self, settings: ApplicationSettings) -> None:
        self._deps.apply_theme(settings.theme)
        self._deps.apply_language(settings.language)
        self._deps.set_sidebar_mode(settings.sidebar_mode)
        self._deps.set_log_panel_visible(settings.show_log_panel)
        self._deps.configure_performance_monitor(
            settings.enable_performance_monitor,
            float(settings.performance_print_interval),
        )

    def _set_operation_busy(self, busy: bool) -> None:
        self._operation_busy = busy
        self.disabled = busy
        safe_update(self)

    def _dispatch_result(self, callback: Callable[[], None]) -> None:
        if self._disposed:
            return
        try:
            page = self.page
        except RuntimeError:
            page = None
        if page is None:
            callback()
            return
        run_on_ui(page, callback)

    def did_mount(self) -> None:
        """挂载后异步读取缓存统计，避免构建控件树时执行 I/O。"""
        self._refresh_cache_stats()

    def dispose(self) -> None:
        """取消后台操作并使迟到结果失效；可重复调用。"""
        if self._disposed:
            return
        self._disposed = True
        self._operation_busy = False
        self._io_controller.close()

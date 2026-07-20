"""Settings View —— 应用配置界面

每个设置分区支持点击标题栏展开/收起，减少纵向占用。
"""
from dataclasses import dataclass
from typing import Callable, Optional

import flet as ft

from app.models.config import ApplicationSettings
from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.components.buttons import btn_ghost
from app.ui.components.fields import text_field, checkbox, label, dropdown
from app.ui.components.cards import card
from app.ui.components.layout import page_header
from app.ui.views.settings_sections import collapsible_section as _collapsible_section
from app.ui.utils import safe_update


Translate = Callable[..., str]
DialogCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class SettingsViewDependencies:
    """设置页与应用壳层之间的显式端口。"""

    load_settings: Callable[[], ApplicationSettings]
    save_settings: Callable[[ApplicationSettings], None]
    reset_settings: Callable[[], None]
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


class SettingsView(ft.Column):
    """配置设置视图（可折叠分区）"""

    def __init__(self, dependencies: SettingsViewDependencies) -> None:
        super().__init__(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.expand = True
        self._deps = dependencies
        self._build()

    @property
    def _t(self) -> Translate:
        return self._deps.translate

    def _settings(self) -> ApplicationSettings:
        return self._deps.load_settings()

    def _build(self) -> None:
        self.controls.clear()
        self.controls.append(page_header(
            "设置",
            ft.Text("管理通用选项、界面偏好、批量处理和清理规则", size=12, color=THEME.text_muted),
            icon=IconSet.SETTINGS,
        ))
        self._build_general_card()
        self._build_ui_card()
        self._build_cache_card()
        self._build_batch_card()
        self._build_cleanup_card()
        self._build_action_card()

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

        self.controls.append(_collapsible_section(
            self._t("settings.general.title", "通用设置"),
            body,
            expanded=True,  # 默认展开
        ))

    # ─── 界面设置 ───────────────────────────────

    def _build_ui_card(self) -> None:
        cfg = self._settings()
        body = ft.Column(spacing=0)

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
            on_change=lambda _: self._on_language_change(
                self._lang_dropdown.value or "zh_CN"
            ),
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
            value=cfg.sidebar_mode,
            width=120,
            on_change=lambda _: self._on_sidebar_mode_change(
                self._sidebar_mode_dropdown.value or "auto"
            ),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.sidebar_mode", "侧边栏模式")),
                self._sidebar_mode_dropdown,
            ], spacing=4),
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._minecraft_dir_field = text_field(
            value=cfg.minecraft_dir,
            hint_text=self._t(
                "settings.ui.minecraft_dir_hint",
                r"例如 F:\Game\minecraft\.minecraft（可留空自动推断）",
            ),
            expand=True,
            on_change=lambda _: self._on_minecraft_dir_change(),
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                label(self._t("settings.ui.minecraft_dir", "Minecraft 目录")),
                ft.Row(
                    [
                        self._minecraft_dir_field,
                        btn_ghost(
                            self._t("settings.ui.browse", "浏览"),
                            height=36,
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
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

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
        body.controls.append(ft.Container(
            content=ft.Column([
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
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._auto_clear_var = checkbox(
            self._t("settings.ui.auto_clear_log", "自动清除旧日志"),
            value=cfg.auto_clear_log,
            on_change=lambda _: self._on_auto_clear_change(
                bool(self._auto_clear_var.value)
            ),
        )
        body.controls.append(ft.Container(
            content=self._auto_clear_var,
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._show_log_panel_var = checkbox(
            self._t("settings.ui.show_log_panel", "显示悬浮日志面板"),
            value=cfg.show_log_panel,
            on_change=lambda _: self._on_show_log_panel_change(
                bool(self._show_log_panel_var.value)
            ),
        )
        body.controls.append(ft.Container(
            content=self._show_log_panel_var,
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._perf_monitor_var = checkbox(
            self._t("settings.ui.enable_performance_monitor", "启用性能监控"),
            value=cfg.enable_performance_monitor,
            on_change=lambda _: self._on_perf_monitor_change(
                bool(self._perf_monitor_var.value)
            ),
        )
        body.controls.append(ft.Container(
            content=self._perf_monitor_var,
            padding=ft.Padding(left=16, right=16, bottom=8),
        ))

        self._perf_print_interval_field = text_field(
            value=str(cfg.performance_print_interval),
            width=100, expand=False,
            on_change=lambda _: self._on_perf_interval_change(),
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

    # ─── 地图缓存 ───────────────────────────────

    def _build_cache_card(self) -> None:
        body = ft.Column(spacing=0)

        body.controls.append(ft.Container(
            content=ft.Text(
                self._t(
                    "settings.cache.description",
                    "区域地图俯视图会缓存到本地磁盘，加快再次打开速度。"
                    " 可在此查看占用空间并清理。",
                ),
                size=12,
                color=THEME.text_muted,
            ),
            padding=ft.Padding(left=16, right=16, bottom=8, top=10),
        ))

        self._cache_summary = ft.Text(
            self._cache_summary_text(),
            size=13,
            color=THEME.text_primary,
            font_family="monospace",
        )
        self._cache_path_label = ft.Text(
            self._cache_path_text(),
            size=11,
            color=THEME.text_muted,
            selectable=True,
        )
        body.controls.append(ft.Container(
            content=ft.Column([
                self._cache_summary,
                self._cache_path_label,
            ], spacing=6),
            padding=ft.Padding(left=16, right=16, bottom=10),
        ))

        btn_row = ft.Row(
            [
                btn_ghost(
                    self._t("settings.cache.refresh", "刷新"),
                    width=100,
                    height=32,
                    on_click=lambda e: self._refresh_cache_stats(),
                ),
                btn_ghost(
                    self._t("settings.cache.clear", "清理缓存"),
                    width=120,
                    height=32,
                    on_click=lambda e: self._clear_map_cache(),
                ),
            ],
            spacing=10,
        )
        body.controls.append(ft.Container(
            content=btn_row,
            padding=ft.Padding(left=16, right=16, bottom=16),
        ))

        self.controls.append(_collapsible_section(
            self._t("settings.cache.title", "地图缓存"),
            body,
            expanded=True,
        ))

    def _cache_summary_text(self) -> str:
        try:
            from core.mca.tile_cache import get_cache_stats
            from app.ui.utils import format_size

            s = get_cache_stats()
            size_txt = format_size(int(s.get("total_bytes", 0) or 0))
            files = int(s.get("file_count", 0) or 0)
            mem = int(s.get("memory_chunks", 0) or 0)
            return (
                f"磁盘: {size_txt} · {files} 个瓦片文件"
                f"  |  内存解码缓存: {mem} 个 chunk"
            )
        except Exception as ex:
            return f"无法读取缓存信息: {ex}"

    def _cache_path_text(self) -> str:
        try:
            from core.mca.tile_cache import get_cache_stats

            return f"路径: {get_cache_stats().get('path', '')}"
        except Exception:
            return "路径: —"

    def _refresh_cache_stats(self) -> None:
        try:
            self._cache_summary.value = self._cache_summary_text()
            self._cache_path_label.value = self._cache_path_text()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self._cache_summary)
        safe_update(self._cache_path_label)

    def _clear_map_cache(self) -> None:
        try:
            from core.mca.tile_cache import clear_all_caches
            from app.ui.utils import format_size

            result = clear_all_caches()
            deleted = int(result.get("deleted_files", 0) or 0)
            freed = format_size(int(result.get("freed_bytes", 0) or 0))
            mem = int(result.get("memory_chunks_cleared", 0) or 0)
            self._refresh_cache_stats()
            self._deps.info_dialog(
                self._t("dialogs.success", "成功"),
                f"已清理地图缓存：{deleted} 个文件（{freed}），内存 chunk {mem} 条",
            )
        except Exception as ex:
            self._deps.error_dialog(
                self._t("dialogs.error", "错误"),
                f"清理缓存失败: {ex}",
            )

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

        self.controls.append(_collapsible_section(
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

    def _persist(self) -> None:
        """通过配置端口持久化当前设置。"""
        self._deps.save_settings(self._collect_settings())

    def _on_version_detection_change(self, value: bool) -> None:
        del value
        self._persist()

    def _on_theme_change(self, theme: str) -> None:
        self._persist()
        self._deps.apply_theme(theme)

    def _on_sidebar_mode_change(self, mode: str) -> None:
        self._persist()
        self._deps.set_sidebar_mode(mode)

    def _on_language_change(self, lang: str) -> None:
        self._persist()
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

    def _browse_minecraft_dir(self, e: ft.ControlEvent = None) -> None:
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
        self._persist()
        self._deps.set_log_panel_visible(value)

    def _on_perf_monitor_change(self, value: bool) -> None:
        self._persist()
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
        self._deps.set_performance_interval(interval)
        self._persist()

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
        self._cleanup_field.update()
        self._persist()

    def _reset(self) -> None:
        self._deps.reset_settings()
        self._deps.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t("settings.messages.reset_success", "已恢复默认设置"),
        )
        self._build()

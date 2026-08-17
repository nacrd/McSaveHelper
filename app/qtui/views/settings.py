"""设置视图（Qt 版，对应 Flet 树同名视图）。

每个设置分区支持点击标题栏展开/收起，减少纵向占用。
领域逻辑复用 ``app.controllers.settings_io_controller`` 与
``app.presenters.settings_view_state``。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.adapters.file_dialogs import FileType
from app.controllers.settings_io_controller import (
    CacheClearOutcome,
    SettingsCacheSnapshot,
    SettingsIOController,
    SettingsIOControllerDependencies,
)
from app.models.config import ApplicationSettings
from app.presenters.runtime_observability import (
    format_cache_registry_report,
    format_diagnostic_report,
    format_runtime_snapshot,
    format_ui_delivery_summary,
)
from app.presenters.settings_view_state import (
    SettingsFeedbackPhase,
    SettingsViewState,
    begin_reset,
    complete_reset,
    dispose_settings_state,
    mark_save_failed,
    mark_save_pending,
    mark_save_succeeded,
)
from app.qtui.components.buttons import btn_ghost
from app.qtui.components.cards import card, muted_label
from app.qtui.components.fields import checkbox, dropdown, text_field
from app.qtui.components.layout import page_header
from app.qtui.icons import glyph
from app.qtui.utils import format_size, run_on_ui
from app.services.cache_registry import CacheRegistryStats
from app.services.execution_runtime import ExecutionRuntime, ExecutionRuntimeSnapshot
from app.services.operation_metrics import UiDeliveryMetricsSummary

Translate = Callable[..., str]
DialogCallback = Callable[[str, str], None]
CacheSnapshot = Callable[[], CacheRegistryStats]
CacheClear = Callable[[], Mapping[str, int]]
SETTINGS_STACK_BREAKPOINT = 960


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
    save_file: Callable[[str, str, Optional[list[FileType]]], Optional[str]]
    cache_snapshot: CacheSnapshot
    clear_caches: CacheClear
    cache_path: Callable[[], str]
    execution_runtime: ExecutionRuntime
    runtime_snapshot: Callable[[], Optional[ExecutionRuntimeSnapshot]]
    ui_delivery_summary: Callable[[], UiDeliveryMetricsSummary]
    save_debounce_seconds: float = 0.35


class CollapsibleSection(QFrame):
    """可点击标题展开/收起的设置分区。"""

    def __init__(self, title: str, content: QWidget, *, expanded: bool = True) -> None:
        """构建可折叠分区。

        Args:
            title: 分区标题。
            content: 分区内容控件。
            expanded: 是否默认展开。
        """
        super().__init__()
        self._title = title
        self._expanded = expanded
        self.setProperty("role", "card")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._toggle = QPushButton()
        self._toggle.setProperty("role", "sectionToggle")
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._on_toggle)
        root.addWidget(self._toggle)

        self._content_host = QWidget()
        content_layout = QVBoxLayout(self._content_host)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(content)
        root.addWidget(self._content_host)
        self._render_state()

    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        self._render_state()

    def _render_state(self) -> None:
        """同步标题图标、展开属性和内容可见性。"""
        icon = glyph("CHEVRON_DOWN" if self._expanded else "CHEVRON_RIGHT")
        self._toggle.setText(f"{icon}  {self._title}")
        self._toggle.setProperty("expanded", self._expanded)
        self._content_host.setVisible(self._expanded)
        style = self._toggle.style()
        style.unpolish(self._toggle)
        style.polish(self._toggle)


class SettingsView(QScrollArea):
    """配置设置视图（可折叠分区）。"""

    def __init__(self, dependencies: SettingsViewDependencies) -> None:
        """通过显式依赖端口构建设置页。

        Args:
            dependencies: 设置读写、主题/语言应用与对话框等壳层端口。
        """
        super().__init__()
        self._deps = dependencies
        self._state = SettingsViewState()
        self._columns_layout: QBoxLayout | None = None
        self._io_controller = SettingsIOController(
            SettingsIOControllerDependencies(
                execution_runtime=dependencies.execution_runtime,
                save_settings=dependencies.save_settings,
                reset_settings=dependencies.reset_settings,
                cache_snapshot=dependencies.cache_snapshot,
                clear_caches=dependencies.clear_caches,
                cache_path=dependencies.cache_path,
                runtime_snapshot=dependencies.runtime_snapshot,
                ui_delivery_summary=dependencies.ui_delivery_summary,
                build_diagnostic_report=lambda snapshot: format_diagnostic_report(
                    snapshot,
                    format_size=format_size,
                    translate=self._t,
                ),
                dispatch=self._dispatch_result,
                save_debounce_seconds=dependencies.save_debounce_seconds,
            )
        )

        self.setWidgetResizable(True)
        self._build()

    @property
    def _t(self) -> Translate:
        return self._deps.translate

    def _settings(self) -> ApplicationSettings:
        return self._deps.load_settings()

    def _build(self) -> None:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # 页头 + 保存状态
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(page_header(
            "设置",
            "管理通用选项、界面偏好、批量处理和清理规则",
            icon=glyph("SETTINGS"),
        ), 1)
        status_text, _icon, status = self._feedback_projection()
        self._save_status_label = QLabel(status_text)
        self._save_status_label.setProperty("role", "statusChip")
        self._save_status_label.setProperty("feedbackStatus", status)
        header_layout.addWidget(
            self._save_status_label,
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )
        layout.addWidget(header_row)

        # 两个内容列
        self._sections: list[QWidget] = []
        self._build_general_card()
        self._build_ui_card()
        self._build_cache_card()
        self._build_batch_card()
        self._build_cleanup_card()
        self._build_action_card()

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)
        for index in (0, 2, 3):
            left_layout.addWidget(self._sections[index])

        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)
        for index in (1, 4, 5):
            right_layout.addWidget(self._sections[index])

        columns = QWidget()
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(16)
        columns_layout.addWidget(left_column, 1)
        columns_layout.addWidget(right_column, 1)
        self._columns_layout = columns_layout
        layout.addWidget(columns)

        layout.addStretch(1)
        self.setWidget(content)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窄窗口时将设置分区改为单列，避免表单控件互相挤压。"""
        super().resizeEvent(event)
        if self._columns_layout is None:
            return
        width = self.viewport().width()
        direction = (
            QBoxLayout.Direction.TopToBottom
            if width < SETTINGS_STACK_BREAKPOINT
            else QBoxLayout.Direction.LeftToRight
        )
        if self._columns_layout.direction() != direction:
            self._columns_layout.setDirection(direction)

    # ─── 通用设置 ───────────────────────────────

    def _build_general_card(self) -> None:
        cfg = self._settings()
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 0, 16, 16)
        body_layout.setSpacing(10)

        self._version_var = checkbox(
            self._t("settings.general.version_detection", "启用版本自动检测"),
            value=cfg.version_detection,
            on_changed=self._persist_checkbox,
        )
        body_layout.addWidget(self._version_var)

        self._api_timeout_field = text_field(
            value=str(cfg.api_timeout),
            width=100,
            on_changed=lambda _text: self._on_api_timeout_change(),
        )
        body_layout.addWidget(QLabel(
            self._t("settings.general.api_timeout", "API 超时 (秒)")
        ))
        body_layout.addWidget(self._api_timeout_field)

        self._sections.append(CollapsibleSection(
            self._t("settings.general.title", "通用设置"),
            body,
            expanded=True,
        ))

    # ─── 界面设置 ───────────────────────────────

    def _build_ui_card(self) -> None:
        cfg = self._settings()
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 0, 16, 16)
        body_layout.setSpacing(8)

        self._theme_dropdown = dropdown(
            options=["暗色", "浅色"],
            value="暗色" if cfg.theme == "dark" else "浅色",
            width=120,
            on_changed=self._on_theme_change,
        )
        self._theme_dropdown.setProperty("value_key", cfg.theme)
        body_layout.addWidget(QLabel(self._t("settings.ui.theme", "主题")))
        body_layout.addWidget(self._theme_dropdown)

        self._lang_dropdown = dropdown(
            options=["简体中文", "English"],
            value="简体中文" if cfg.language == "zh_CN" else "English",
            width=120,
            on_changed=self._on_language_change,
        )
        self._lang_dropdown.setProperty("value_key", cfg.language)
        body_layout.addWidget(QLabel(self._t("settings.ui.language", "语言")))
        body_layout.addWidget(self._lang_dropdown)

        self._sidebar_mode_dropdown = dropdown(
            options=["展开", "收窄", "自动"],
            value=self._sidebar_mode_label(cfg.sidebar_mode),
            width=120,
            on_changed=self._on_sidebar_mode_change,
        )
        self._sidebar_mode_dropdown.setProperty("value_key", cfg.sidebar_mode)
        body_layout.addWidget(QLabel(
            self._t("settings.ui.sidebar_mode", "侧边栏模式")
        ))
        body_layout.addWidget(self._sidebar_mode_dropdown)

        dir_row = QWidget()
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(8)
        self._minecraft_dir_field = text_field(
            value=cfg.minecraft_dir,
            hint_text=self._t(
                "settings.ui.minecraft_dir_hint",
                r"例如 F:\Game\minecraft\.minecraft（可留空自动推断）",
            ),
            on_changed=self._persist_text,
        )
        browse_button = btn_ghost(
            self._t("settings.ui.browse", "浏览"),
            on_click=self._browse_minecraft_dir,
        )
        dir_layout.addWidget(self._minecraft_dir_field, 1)
        dir_layout.addWidget(browse_button)
        body_layout.addWidget(QLabel(
            self._t("settings.ui.minecraft_dir", "Minecraft 目录")
        ))
        body_layout.addWidget(dir_row)
        body_layout.addWidget(muted_label(
            self._t(
                "settings.ui.minecraft_dir_help",
                "用于导入语言/贴图。优先此路径；留空则从当前存档向上查找 "
                ".minecraft，或使用系统默认目录。",
            )
        ))

        self._auto_import_mc_lang_var = checkbox(
            self._t(
                "settings.ui.auto_import_mc_lang",
                "设置存档后自动导入 Minecraft 语言",
            ),
            value=cfg.auto_import_mc_lang,
            on_changed=self._persist_checkbox,
        )
        body_layout.addWidget(self._auto_import_mc_lang_var)

        self._auto_clear_var = checkbox(
            self._t("settings.ui.auto_clear_log", "自动清除旧日志"),
            value=cfg.auto_clear_log,
            on_changed=self._persist_checkbox,
        )
        body_layout.addWidget(self._auto_clear_var)

        self._show_log_panel_var = checkbox(
            self._t("settings.ui.show_log_panel", "显示悬浮日志面板"),
            value=cfg.show_log_panel,
            on_changed=self._on_show_log_panel_change,
        )
        body_layout.addWidget(self._show_log_panel_var)

        self._perf_monitor_var = checkbox(
            self._t("settings.ui.enable_performance_monitor", "启用性能监控"),
            value=cfg.enable_performance_monitor,
            on_changed=self._on_perf_monitor_change,
        )
        body_layout.addWidget(self._perf_monitor_var)

        self._perf_print_interval_field = text_field(
            value=str(cfg.performance_print_interval),
            width=100,
            on_changed=lambda _text: self._on_perf_interval_change(),
        )
        body_layout.addWidget(QLabel(
            self._t(
                "settings.ui.performance_print_interval",
                "性能日志打印间隔 (秒)",
            )
        ))
        body_layout.addWidget(self._perf_print_interval_field)

        self._sections.append(CollapsibleSection(
            self._t("settings.ui.title", "界面设置"),
            body,
            expanded=True,
        ))

    @staticmethod
    def _sidebar_mode_label(mode: str) -> str:
        return {"expanded": "展开", "collapsed": "收窄", "auto": "自动"}.get(
            mode,
            "自动",
        )

    # ─── 应用缓存 ───────────────────────────────

    def _build_cache_card(self) -> None:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 0, 16, 16)
        body_layout.setSpacing(8)

        body_layout.addWidget(muted_label(
            self._t(
                "settings.cache.description",
                "统一管理世界索引、纹理和地图渲染缓存；内存受总预算约束，"
                "地图瓦片仍持久化到本地以加快再次打开。",
            )
        ))
        self._cache_summary = QLabel(
            self._t("settings.cache.loading", "正在读取缓存信息…")
        )
        self._runtime_summary = QLabel(
            self._t("settings.cache.runtime_loading", "正在读取后台运行时…")
        )
        self._ui_delivery_summary = QLabel(
            self._t("settings.cache.ui_delivery_loading", "正在读取 UI 投递指标…")
        )
        self._cache_path_label = QLabel(
            self._t("settings.cache.path_loading", "地图瓦片路径: —")
        )
        for label_widget in (
            self._cache_summary,
            self._runtime_summary,
            self._ui_delivery_summary,
            self._cache_path_label,
        ):
            label_widget.setWordWrap(True)
            label_widget.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            body_layout.addWidget(label_widget)

        actions_row = QWidget()
        actions_layout = QHBoxLayout(actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(10)
        self._cache_refresh_button = btn_ghost(
            self._t("settings.cache.refresh", "刷新"),
            width=100,
            on_click=lambda: self._refresh_cache_stats(show_error=True),
        )
        self._cache_clear_button = btn_ghost(
            self._t("settings.cache.clear", "清理缓存"),
            width=120,
            on_click=self._clear_map_cache,
        )
        self._cache_export_button = btn_ghost(
            self._t("settings.cache.export", "导出诊断报告"),
            width=140,
            on_click=self._export_diagnostic_report,
        )
        actions_layout.addWidget(self._cache_refresh_button)
        actions_layout.addWidget(self._cache_clear_button)
        actions_layout.addWidget(self._cache_export_button)
        actions_layout.addStretch(1)
        body_layout.addWidget(actions_row)

        self._sections.append(CollapsibleSection(
            self._t("settings.cache.title", "应用缓存"),
            body,
            expanded=True,
        ))

    def _refresh_cache_stats(self, *, show_error: bool = False) -> None:
        if self._state.is_disposed:
            return
        self._set_cache_busy(True)
        self._io_controller.refresh_cache(
            self._apply_cache_snapshot,
            lambda error: self._apply_cache_error(error, show_error),
        )

    def _apply_cache_snapshot(self, snapshot: SettingsCacheSnapshot) -> None:
        if self._state.is_disposed:
            return
        self._set_cache_busy(False)
        self._cache_summary.setText(format_cache_registry_report(
            snapshot.cache,
            format_size=format_size,
        ))
        self._runtime_summary.setText(
            format_runtime_snapshot(snapshot.runtime)
            if snapshot.runtime is not None
            else self._t("settings.cache.runtime_unavailable", "后台运行时: 不可用")
        )
        self._ui_delivery_summary.setText(format_ui_delivery_summary(
            snapshot.ui_delivery,
            translate=self._t,
        ))
        self._cache_path_label.setText(self._t(
            "settings.cache.path_value",
            "地图瓦片路径: {path}",
            path=snapshot.cache_path,
        ))

    def _apply_cache_error(self, error: Exception, show_error: bool) -> None:
        if self._state.is_disposed:
            return
        self._set_cache_busy(False)
        self._cache_summary.setText(self._t(
            "settings.cache.read_failed",
            "无法读取缓存信息: {error}",
            error=str(error),
        ))
        if show_error:
            self._deps.error_dialog(
                self._t("dialogs.error", "错误"),
                str(error),
            )

    def _clear_map_cache(self) -> None:
        if self._state.is_disposed:
            return
        self._set_cache_busy(True)
        self._io_controller.clear_cache(
            self._apply_cache_clear_success,
            lambda error: self._apply_cache_error(error, True),
        )

    def _export_diagnostic_report(self) -> None:
        if self._state.is_disposed:
            return
        path = self._deps.save_file(
            self._t("settings.cache.export_title", "保存诊断报告"),
            ".txt",
            [
                (self._t("settings.cache.export_file", "文本文件"), "*.txt"),
            ],
        )
        if not path:
            return
        self._set_cache_busy(True)
        self._io_controller.export_diagnostic_report(
            path,
            self._apply_diagnostic_export_success,
            lambda error: self._apply_cache_error(error, True),
        )

    def _apply_diagnostic_export_success(self, path: Path) -> None:
        if self._state.is_disposed:
            return
        self._set_cache_busy(False)
        self._deps.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t(
                "settings.cache.export_success",
                "诊断报告已导出到 {path}",
                path=str(path),
            ),
        )

    def _apply_cache_clear_success(self, outcome: CacheClearOutcome) -> None:
        if self._state.is_disposed:
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
        self._cache_refresh_button.setEnabled(not busy)
        self._cache_clear_button.setEnabled(not busy)
        self._cache_export_button.setEnabled(not busy)

    # ─── 批量处理 ───────────────────────────────

    def _build_batch_card(self) -> None:
        cfg = self._settings()
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 0, 16, 16)
        body_layout.setSpacing(8)

        self._max_concurrent_field = text_field(
            value=str(cfg.max_concurrent),
            width=100,
            on_changed=lambda _text: self._on_max_concurrent_change(),
        )
        body_layout.addWidget(QLabel(
            self._t("settings.batch.max_concurrent", "最大并发处理数 (1‑16)")
        ))
        body_layout.addWidget(self._max_concurrent_field)

        self._preserve_var = checkbox(
            self._t("settings.batch.preserve_structure", "保留原始文件结构"),
            value=cfg.preserve_structure,
            on_changed=self._persist_checkbox,
        )
        body_layout.addWidget(self._preserve_var)

        self._sections.append(CollapsibleSection(
            self._t("settings.batch.title", "批量处理"),
            body,
            expanded=False,
        ))

    # ─── 清理模式 ───────────────────────────────

    def _build_cleanup_card(self) -> None:
        cfg = self._settings()
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 0, 16, 16)
        body_layout.setSpacing(8)

        body_layout.addWidget(muted_label(
            self._t(
                "settings.cleanup.description",
                "转换完成后自动删除的文件/目录模式（每行一个，支持通配符）",
            )
        ))
        self._cleanup_field = QPlainTextEdit()
        self._cleanup_field.setPlainText("\n".join(cfg.cleanup_patterns))
        self._cleanup_field.setMinimumHeight(90)
        body_layout.addWidget(self._cleanup_field)

        restore_button = btn_ghost(
            self._t("settings.cleanup.restore_defaults", "恢复默认"),
            width=120,
            on_click=self._restore_default_cleanup,
        )
        body_layout.addWidget(restore_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self._sections.append(CollapsibleSection(
            self._t("settings.cleanup.title", "清理模式"),
            body,
            expanded=False,
        ))

    # ─── 操作按钮 ───────────────────────────────

    def _build_action_card(self) -> None:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        reset_button = QPushButton("↻ 重置为默认")
        reset_button.setProperty("role", "warning")
        reset_button.clicked.connect(lambda: self._reset())
        body_layout.addWidget(reset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self._sections.append(card(body, padding=0))

    def refresh_theme(self) -> None:
        """刷新设置页中随主题变化的反馈色。"""
        self._render_feedback_state()

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
            self._perf_print_interval_field.text(),
            60,
            5,
            86400,
        )

    def _collect_settings(self) -> ApplicationSettings:
        """从控件读取并校验一份完整设置快照。"""
        return ApplicationSettings(
            version_detection=bool(self._version_var.isChecked()),
            api_timeout=self._bounded_int(
                self._api_timeout_field.text(),
                10,
                1,
                60,
            ),
            theme=str(self._theme_dropdown.property("value_key") or "dark"),
            language=str(self._lang_dropdown.property("value_key") or "zh_CN"),
            sidebar_mode=str(
                self._sidebar_mode_dropdown.property("value_key") or "auto"
            ),
            auto_clear_log=bool(self._auto_clear_var.isChecked()),
            show_log_panel=bool(self._show_log_panel_var.isChecked()),
            enable_performance_monitor=bool(self._perf_monitor_var.isChecked()),
            performance_print_interval=self._performance_interval(),
            max_concurrent=self._bounded_int(
                self._max_concurrent_field.text(),
                2,
                1,
                16,
            ),
            preserve_structure=bool(self._preserve_var.isChecked()),
            cleanup_patterns=tuple(
                item.strip()
                for item in self._cleanup_field.toPlainText().splitlines()
                if item.strip()
            ),
            minecraft_dir=self._minecraft_dir_field.text().strip(),
            auto_import_mc_lang=bool(self._auto_import_mc_lang_var.isChecked()),
        )

    def _persist(self) -> bool:
        """提交最新设置快照，并在防抖窗口内合并连续输入。"""
        if not self._state.can_start_operation:
            return False
        try:
            settings = self._collect_settings()
        except Exception as error:
            self._apply_save_error(error)
            return False
        self._state = mark_save_pending(self._state)
        self._render_feedback_state()
        self._io_controller.schedule_save(
            settings,
            self._apply_save_success,
            self._apply_save_error,
        )
        return True

    def _apply_save_success(self) -> None:
        if self._state.is_disposed:
            return
        self._state = mark_save_succeeded(self._state)
        self._render_feedback_state()

    def _apply_save_error(self, error: Exception) -> None:
        if self._state.is_disposed:
            return
        self._state = mark_save_failed(self._state)
        self._render_feedback_state()
        self._deps.error_dialog(
            self._t("dialogs.error", "错误"),
            str(error),
        )

    def _render_feedback_state(self) -> None:
        """把不可变反馈状态投影到保存状态标签。"""
        text, _icon, status = self._feedback_projection()
        self._save_status_label.setText(text)
        self._save_status_label.setProperty("feedbackStatus", status)
        style = self._save_status_label.style()
        style.unpolish(self._save_status_label)
        style.polish(self._save_status_label)

    def _feedback_projection(self) -> tuple[str, str, str]:
        phase = self._state.feedback
        if phase is SettingsFeedbackPhase.PENDING:
            return (
                self._t("settings.save_status.pending", "等待保存"),
                "INFO",
                "pending",
            )
        if phase is SettingsFeedbackPhase.SAVED:
            return (
                self._t("settings.save_status.saved", "已保存"),
                "SUCCESS",
                "saved",
            )
        if phase is SettingsFeedbackPhase.FAILED:
            return (
                self._t("settings.save_status.failed", "保存失败"),
                "ERROR",
                "failed",
            )
        if phase is SettingsFeedbackPhase.RESETTING:
            return (
                self._t("settings.save_status.resetting", "正在重置"),
                "INFO",
                "pending",
            )
        return (
            self._t("settings.save_status.auto", "更改会自动保存"),
            "INFO",
            "neutral",
        )

    # ─── 字段变更处理器 ──────────────────────────

    def _persist_checkbox(self, _value: bool) -> None:
        """复选框变更后持久化（不消费返回值）。"""
        self._persist()

    def _persist_text(self, _text: str) -> None:
        """文本字段变更后持久化（不消费返回值）。"""
        self._persist()

    def _on_theme_change(self, _text: str) -> None:
        index = self._theme_dropdown.currentIndex()
        theme = "dark" if index == 0 else "light"
        self._theme_dropdown.setProperty("value_key", theme)
        if self._persist():
            self._deps.apply_theme(theme)

    def _on_language_change(self, _text: str) -> None:
        index = self._lang_dropdown.currentIndex()
        lang = "zh_CN" if index == 0 else "en_US"
        self._lang_dropdown.setProperty("value_key", lang)
        if self._persist():
            self._deps.apply_language(lang)

    def _on_sidebar_mode_change(self, _text: str) -> None:
        index = self._sidebar_mode_dropdown.currentIndex()
        mode = ("expanded", "collapsed", "auto")[index]
        self._sidebar_mode_dropdown.setProperty("value_key", mode)
        if self._persist():
            self._deps.set_sidebar_mode(mode)

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
                float(self._perf_print_interval_field.text() or "60"),
            )
        except ValueError:
            return
        if self._persist():
            self._deps.set_performance_interval(interval)

    def _on_api_timeout_change(self) -> None:
        try:
            int(self._api_timeout_field.text() or "10")
        except ValueError:
            return
        self._persist()

    def _on_max_concurrent_change(self) -> None:
        try:
            int(self._max_concurrent_field.text() or "2")
        except ValueError:
            return
        self._persist()

    def _browse_minecraft_dir(self) -> None:
        try:
            path = self._deps.pick_directory()
            if not path:
                return
            self._minecraft_dir_field.setText(path)
            self._persist()
        except Exception as exc:
            self._deps.error_dialog(
                self._t("settings.ui.minecraft_dir_error", "选择目录失败"),
                str(exc),
            )

    def _restore_default_cleanup(self) -> None:
        self._cleanup_field.setPlainText("\n".join(["*.log", "cache/", "logs/"]))
        self._persist()

    def _reset(self) -> None:
        if not self._state.can_start_operation:
            return
        self._state = begin_reset(self._state)
        self._render_feedback_state()
        self._io_controller.reset(
            self._apply_reset_success,
            self._apply_reset_error,
        )

    def _apply_reset_success(self, settings: ApplicationSettings) -> None:
        if self._state.is_disposed:
            return
        self._state = complete_reset(self._state)
        self._apply_settings_effects(settings)
        self._build()
        self._render_feedback_state()
        self._refresh_cache_stats()
        self._deps.info_dialog(
            self._t("dialogs.success", "成功"),
            self._t("settings.messages.reset_success", "已恢复默认设置"),
        )

    def _apply_reset_error(self, error: Exception) -> None:
        if self._state.is_disposed:
            return
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

    def _dispatch_result(self, callback: Callable[[], None]) -> None:
        if self._state.is_disposed:
            return
        run_on_ui(callback)

    def did_mount(self) -> None:
        """挂载后异步读取缓存统计，避免构建控件树时执行 I/O。"""
        self._refresh_cache_stats()

    def dispose(self) -> None:
        """取消后台操作并使迟到结果失效；可重复调用。"""
        if self._state.is_disposed:
            return
        self._state = dispose_settings_state(self._state)
        self._io_controller.close()

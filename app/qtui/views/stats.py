"""Qt Explorer 世界统计视图。"""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.presenters.stats_view_state import (
    RankItem,
    StatsViewState,
    build_stats_view_state,
)
from app.qtui.components.cards import muted_label
from app.qtui.utils import format_size
from app.services.world_stats_service import (
    PLAYER_SORT_DAMAGE,
    PLAYER_SORT_DEATHS,
    PLAYER_SORT_DISTANCE,
    PLAYER_SORT_JUMPS,
    PLAYER_SORT_MINED,
    PLAYER_SORT_MOB_KILLS,
    PLAYER_SORT_NAME,
    PLAYER_SORT_OPTIONS,
    PLAYER_SORT_PLACED,
    PLAYER_SORT_PLAY_TIME,
    PLAYER_SORT_PLAYER_KILLS,
    PLAYER_SORT_WORLD_TIME,
    PlayerPlaytimeStats,
    WorldStatistics,
    WorldStatsService,
)
from core.uuid_utils import format_uuid_with_hyphens


Translate = Callable[..., str]
Command = Callable[[], None]


class QtStatsPanel(QWidget):
    """展示世界概览、玩家统计与资源排行。"""

    def __init__(
        self,
        translate: Translate,
        on_start: Command,
        on_cancel: Command,
    ) -> None:
        """构建统计标签。

        Args:
            translate: UI 翻译回调。
            on_start: 开始分析命令。
            on_cancel: 取消分析命令。
        """
        super().__init__()
        self._translate = translate
        self._stats: WorldStatistics | None = None
        self._view_state: StatsViewState | None = None
        self._build(on_start, on_cancel)
        self.show_ready(False)

    @property
    def view_state(self) -> StatsViewState | None:
        """返回最近一次完整统计投影。"""
        return self._view_state

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._translate(key, default, **kwargs)

    def _build(self, on_start: Command, on_cancel: Command) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        self._status = muted_label("")
        toolbar.addWidget(self._status, 1)
        self._start = QPushButton(self._t("stats.start", "开始统计"))
        self._start.setProperty("role", "primary")
        self._start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start.clicked.connect(lambda _checked: on_start())
        toolbar.addWidget(self._start)
        self._cancel = QPushButton(self._t("stats.cancel", "取消"))
        self._cancel.setProperty("role", "ghost")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.clicked.connect(lambda _checked: on_cancel())
        toolbar.addWidget(self._cancel)
        layout.addLayout(toolbar)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        tabs = QTabWidget()
        tabs.addTab(self._build_overview(), self._tab_label(
            "🏠", "stats.tab_overview", "概览"
        ))
        tabs.addTab(self._build_players(), self._tab_label(
            "🧍", "stats.tab_players", "玩家"
        ))
        tabs.addTab(self._build_rankings(), self._tab_label(
            "🏆", "stats.tab_rankings", "排行"
        ))
        layout.addWidget(tabs, 1)

    def _tab_label(self, icon: str, key: str, default: str) -> str:
        """为统计内部 tab 标题加上图标。"""
        return f"{icon}  {self._t(key, default)}"

    def _build_overview(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(QLabel(self._t("stats.section_summary", "汇总")))
        self._summary = self._create_table([
            self._t("stats.column_metric", "指标"),
            self._t("stats.column_value", "值"),
        ])
        layout.addWidget(self._summary, 1)
        layout.addWidget(QLabel(self._t(
            "stats.section_dimensions", "维度大小"
        )))
        self._dimensions = self._create_table([
            self._t("stats.column_dimension", "维度"),
            self._t("stats.column_regions", "区域文件"),
            self._t("stats.column_size", "大小"),
        ])
        layout.addWidget(self._dimensions, 1)
        return host

    def _build_players(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 8, 0, 0)
        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel(self._t("stats.sort_by", "排序")))
        self._sort = QComboBox()
        for key in PLAYER_SORT_OPTIONS:
            self._sort.addItem(self._sort_label(key), key)
        self._sort.setCurrentIndex(
            self._sort.findData(PLAYER_SORT_PLAY_TIME)
        )
        self._sort.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort)
        sort_row.addStretch(1)
        layout.addLayout(sort_row)
        self._players = self._create_table([
            self._t("stats.column_player", "玩家"),
            self._t("stats.column_metric", "指标"),
            self._t("stats.sort_play_time", "游玩时间"),
            self._t("stats.sort_deaths", "死亡"),
            self._t("stats.sort_mob_kills", "生物击杀"),
            self._t("stats.sort_mined", "挖掘"),
            self._t("stats.sort_placed", "使用/放置"),
        ])
        layout.addWidget(self._players, 1)
        return host

    def _build_rankings(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 8, 0, 0)
        self._rankings = self._create_table([
            self._t("stats.column_category", "类别"),
            self._t("stats.column_name", "名称"),
            self._t("stats.column_value", "值"),
        ])
        layout.addWidget(self._rankings)
        return host

    @staticmethod
    def _create_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        return table

    def show_ready(self, has_world: bool) -> None:
        """切换世界后恢复未分析状态。"""
        self._stats = None
        self._view_state = None
        self._clear_tables()
        self._progress.setValue(0)
        self._start.setEnabled(has_world)
        self._cancel.setEnabled(False)
        key = "stats.not_analyzed" if has_world else "stats.no_world"
        default = "尚未分析" if has_world else "未加载存档"
        self._status.setText(self._t(key, default))

    def show_analyzing(self) -> None:
        """显示统计分析运行状态。"""
        self._status.setText(self._t(
            "stats.analyzing", "正在分析，较大存档可能需要较长时间..."
        ))
        self._progress.setValue(0)
        self._start.setEnabled(False)
        self._cancel.setEnabled(True)

    def update_progress(self, value: float, message: str) -> None:
        """投影 0..1 分析进度。"""
        percent = round(max(0.0, min(1.0, value)) * 100)
        self._progress.setValue(percent)
        self._status.setText(f"{message} · {percent}%")

    def show_stats(self, stats: WorldStatistics) -> None:
        """把完整统计结果投影到三个数据视图。"""
        self._stats = stats
        self._view_state = build_stats_view_state(
            stats,
            player_sort_key=self._sort_key(),
            size_formatter=format_size,
        )
        self._fill_summary(stats, self._view_state)
        self._fill_dimensions(self._view_state)
        self._fill_players(self._view_state)
        self._fill_rankings(self._view_state)
        self._progress.setValue(100)
        self._status.setText(self._t("stats.done", "统计完成。"))

    def show_error(self) -> None:
        """显示统计失败状态并保留上一份完整结果。"""
        self._status.setText(self._t("stats.error_status", "统计失败。"))

    def show_cancelled(self) -> None:
        """显示用户取消状态。"""
        self._status.setText(self._t("stats.cancelled", "统计已取消。"))
        self._progress.setValue(0)
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        """切换开始与取消按钮可用性。"""
        self._start.setEnabled(not busy)
        self._cancel.setEnabled(busy)

    def _clear_tables(self) -> None:
        for table in (
            self._summary,
            self._dimensions,
            self._players,
            self._rankings,
        ):
            table.setRowCount(0)

    def _fill_summary(
        self,
        stats: WorldStatistics,
        state: StatsViewState,
    ) -> None:
        slots = state.loaded_chunks + state.empty_chunks
        ratio = state.loaded_chunks / slots * 100 if slots else 0.0
        rows = (
            (self._t("stats.metric_regions", "区域文件"), state.total_regions),
            (self._t("stats.metric_loaded", "已加载区块"), state.loaded_chunks),
            (self._t("stats.metric_empty", "空槽位"), state.empty_chunks),
            (self._t("stats.metric_ratio", "加载比例"), f"{ratio:.1f}%"),
            (
                self._t("stats.metric_region_size", "区域文件大小"),
                format_size(sum(stats.region_sizes.values())),
            ),
            (self._t("stats.metric_dimensions", "维度"), len(state.dimensions)),
            (self._t("stats.metric_players", "玩家统计"), len(state.players)),
            (self._t("stats.metric_blocks", "方块条目"), state.total_blocks),
            (self._t("stats.metric_entities", "实体"), state.total_entities),
        )
        self._set_rows(self._summary, rows)

    def _fill_dimensions(self, state: StatsViewState) -> None:
        rows = (
            (item.display_name, item.region_count, format_size(item.total_bytes))
            for item in state.dimensions
        )
        self._set_rows(self._dimensions, rows)

    def _fill_players(self, state: StatsViewState) -> None:
        rows = (
            (
                player.name or format_uuid_with_hyphens(player.uuid),
                self._format_player_metric(player),
                WorldStatsService.format_ticks_as_duration(
                    player.play_time_ticks
                ),
                player.deaths,
                player.mob_kills,
                player.mined,
                player.placed,
            )
            for player in state.players
        )
        self._set_rows(self._players, rows)

    def _fill_rankings(self, state: StatsViewState) -> None:
        rows: list[tuple[object, ...]] = []
        rows.extend(self._rank_rows(
            self._t("stats.rank_blocks", "方块"), state.top_blocks
        ))
        rows.extend(self._rank_rows(
            self._t("stats.rank_entities", "实体"), state.top_entities
        ))
        rows.extend(self._rank_rows(
            self._t("stats.rank_region_sizes", "区域大小"),
            state.region_size_ranks,
        ))
        self._set_rows(self._rankings, rows)

    @staticmethod
    def _rank_rows(
        category: str,
        items: tuple[RankItem, ...],
    ) -> list[tuple[object, ...]]:
        return [
            (
                category,
                item.label,
                int(item.value) if item.value.is_integer() else item.value,
            )
            for item in items
        ]

    @staticmethod
    def _set_rows(
        table: QTableWidget,
        rows: Iterable[Sequence[object]],
    ) -> None:
        materialized = list(rows)
        table.setRowCount(len(materialized))
        for row_index, row in enumerate(materialized):
            for column, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                table.setItem(row_index, column, item)

    def _on_sort_changed(self, _index: int) -> None:
        stats = self._stats
        if stats is None:
            return
        self._view_state = build_stats_view_state(
            stats,
            player_sort_key=self._sort_key(),
            size_formatter=format_size,
        )
        self._fill_players(self._view_state)

    def _sort_key(self) -> str:
        value = self._sort.currentData(Qt.ItemDataRole.UserRole)
        return str(value) if value in PLAYER_SORT_OPTIONS else PLAYER_SORT_PLAY_TIME

    def _sort_label(self, key: str) -> str:
        labels = {
            PLAYER_SORT_PLAY_TIME: ("stats.sort_play_time", "游玩时间"),
            PLAYER_SORT_WORLD_TIME: ("stats.sort_world_time", "世界时间"),
            PLAYER_SORT_DEATHS: ("stats.sort_deaths", "死亡"),
            PLAYER_SORT_MOB_KILLS: ("stats.sort_mob_kills", "生物击杀"),
            PLAYER_SORT_PLAYER_KILLS: ("stats.sort_player_kills", "玩家击杀"),
            PLAYER_SORT_MINED: ("stats.sort_mined", "挖掘"),
            PLAYER_SORT_PLACED: ("stats.sort_placed", "使用/放置"),
            PLAYER_SORT_JUMPS: ("stats.sort_jumps", "跳跃"),
            PLAYER_SORT_DAMAGE: ("stats.sort_damage", "造成伤害"),
            PLAYER_SORT_DISTANCE: ("stats.sort_distance", "移动距离"),
            PLAYER_SORT_NAME: ("stats.sort_name", "名称"),
        }
        translation_key, default = labels[key]
        return self._t(translation_key, default)

    def _format_player_metric(self, player: PlayerPlaytimeStats) -> str:
        key = self._sort_key()
        if key == PLAYER_SORT_PLAY_TIME:
            return WorldStatsService.format_ticks_as_duration(
                player.play_time_ticks
            )
        if key == PLAYER_SORT_WORLD_TIME:
            return WorldStatsService.format_ticks_as_duration(
                player.total_world_time_ticks
            )
        if key == PLAYER_SORT_DISTANCE:
            return self._t(
                "stats.metric_distance",
                "{meters:.1f} m",
                meters=player.distance_cm / 100.0,
            )
        if key == PLAYER_SORT_NAME:
            return player.name or format_uuid_with_hyphens(player.uuid)
        return str(WorldStatsService.player_metric_value(player, key))


def format_stats_stage(
    translate: Translate,
    stage: str,
) -> str:
    """把服务进度阶段转换为用户文本。"""
    keys = {
        "dimensions": ("stats.stage_dimensions", "统计维度大小"),
        "players": ("stats.stage_players", "读取玩家游玩时间"),
        "scanning": ("stats.stage_scanning", "扫描区域文件"),
        "finalizing": ("stats.stage_finalizing", "汇总结果"),
        "done": ("stats.stage_done", "完成"),
    }
    if stage.startswith("regions:"):
        parts = stage.split(":")
        if len(parts) == 3:
            return translate(
                "stats.stage_regions",
                "分析区域 {done}/{total}",
                done=parts[1],
                total=parts[2],
            )
    key, default = keys.get(stage, ("stats.progress_task", "统计存档"))
    return translate(key, default)


__all__ = ["QtStatsPanel", "format_stats_stage"]

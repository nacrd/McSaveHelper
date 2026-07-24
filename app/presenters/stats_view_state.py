"""不可变统计页 ViewState 与纯投影。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence

from app.services.world_stats_service import (
    DimensionSizeStats,
    PlayerPlaytimeStats,
    WorldStatistics,
    WorldStatsService,
)


@dataclass(frozen=True)
class RankItem:
    """排行榜单项。"""

    label: str
    value: float


@dataclass(frozen=True)
class StatsViewState:
    """统计 Tab 一次渲染可消费的不可变快照。"""

    summary_lines: tuple[str, ...]
    top_blocks: tuple[RankItem, ...]
    top_entities: tuple[RankItem, ...]
    region_size_ranks: tuple[RankItem, ...]
    dimensions: tuple[DimensionSizeStats, ...]
    players: tuple[PlayerPlaytimeStats, ...]
    loaded_chunks: int
    empty_chunks: int
    total_regions: int
    total_blocks: int
    total_entities: int


@dataclass(frozen=True)
class StatsAnalysisState:
    """Ownership snapshot for one Explorer statistics analysis."""

    generation: int = 0
    host_generation: int = -1
    world_path: Path | None = None
    is_running: bool = False


def begin_stats_analysis(
    state: StatsAnalysisState,
    world_path: Path,
    host_generation: int,
) -> StatsAnalysisState:
    """Start a new statistics generation for one world identity."""
    return StatsAnalysisState(
        generation=state.generation + 1,
        host_generation=host_generation,
        world_path=world_path,
        is_running=True,
    )


def finish_stats_analysis(
    state: StatsAnalysisState,
    generation: int,
) -> StatsAnalysisState:
    """Release matching analysis ownership and ignore stale completions."""
    if generation != state.generation or not state.is_running:
        return state
    return replace(state, is_running=False)


def invalidate_stats_analysis(state: StatsAnalysisState) -> StatsAnalysisState:
    """Invalidate pending results after a world or lifecycle change."""
    return StatsAnalysisState(generation=state.generation + 1)


def owns_stats_analysis(
    state: StatsAnalysisState,
    generation: int,
    world_path: Path,
    host_generation: int,
) -> bool:
    """Return whether a callback still belongs to the latest analysis."""
    return (
        generation == state.generation
        and host_generation == state.host_generation
        and world_path == state.world_path
    )


def _rank_items(
    pairs: Sequence[tuple[str, float | int]],
    *,
    limit: int,
) -> tuple[RankItem, ...]:
    items = [
        RankItem(label=str(label), value=float(value))
        for label, value in pairs[:limit]
    ]
    return tuple(items)


def build_stats_view_state(
    stats: WorldStatistics,
    *,
    player_sort_key: str,
    size_formatter: Callable[[int], str] | None = None,
    top_limit: int = 10,
) -> StatsViewState:
    """从 ``WorldStatistics`` 构造 UI 投影状态。

    Args:
        stats: 分析服务返回的统计结果。
        player_sort_key: 玩家排序键。
        size_formatter: 可选 ``bytes -> str``；默认简单 ``N B``。
        top_limit: 排行截断条数。
    """
    format_size = size_formatter or (lambda n: f"{int(n)} B")
    chunk_slots = stats.loaded_chunks + stats.empty_chunks
    loaded_ratio = (
        stats.loaded_chunks / chunk_slots * 100 if chunk_slots else 0.0
    )
    total_size = sum(stats.region_sizes.values())
    dim_total = sum(item.total_bytes for item in stats.dimension_stats)
    summary = (
        f"regions={stats.total_regions}",
        f"loaded={stats.loaded_chunks}",
        f"empty={stats.empty_chunks}",
        f"ratio={loaded_ratio:.1f}",
        f"region_size={format_size(total_size)}",
        f"dimensions={len(stats.dimension_stats)}",
        f"dim_size={format_size(dim_total)}",
        f"players={len(stats.player_stats)}",
        f"blocks={stats.total_blocks}",
        f"entities={stats.total_entities}",
    )
    block_items = stats.block_stats.top_blocks if stats.block_stats else []
    entity_items = (
        stats.entity_stats.top_entities if stats.entity_stats else []
    )
    size_dist = WorldStatsService.get_region_size_distribution(stats)
    players = WorldStatsService.sort_player_stats(
        list(stats.player_stats),
        player_sort_key,
    )
    return StatsViewState(
        summary_lines=summary,
        top_blocks=_rank_items(block_items, limit=top_limit),
        top_entities=_rank_items(entity_items, limit=top_limit),
        region_size_ranks=_rank_items(
            list(size_dist.items()),
            limit=top_limit,
        ),
        dimensions=tuple(stats.dimension_stats),
        players=tuple(players),
        loaded_chunks=stats.loaded_chunks,
        empty_chunks=stats.empty_chunks,
        total_regions=stats.total_regions,
        total_blocks=stats.total_blocks,
        total_entities=stats.total_entities,
    )


__all__ = [
    "RankItem",
    "StatsAnalysisState",
    "StatsViewState",
    "begin_stats_analysis",
    "build_stats_view_state",
    "finish_stats_analysis",
    "invalidate_stats_analysis",
    "owns_stats_analysis",
]

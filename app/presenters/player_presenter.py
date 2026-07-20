"""Format player summaries for export (no Flet)."""
from __future__ import annotations

from typing import Callable, Optional

from app.services.player.models import PlayerExportBundle, PlayerSummary

Translate = Callable[..., str]


def format_player_summary_text(
    summary: PlayerSummary,
    translate: Optional[Translate] = None,
) -> str:
    """Human-readable multi-line player summary."""
    t = translate or (lambda key, default="", **_kw: default or key)
    ref = summary.ref
    state = summary.state
    pose = summary.pose
    lines = [
        t("player.export.title", "玩家摘要"),
        f"{t('player.export.name', '名称')}: {ref.display_name}",
        f"UUID: {ref.uuid_hyphen or ref.uuid_norm}",
        f"{t('player.export.health', '生命')}: {_fmt(state.health)}",
        f"{t('player.export.food', '饥饿')}: {_fmt(state.food_level)}",
        f"{t('player.export.xp', '经验等级')}: {_fmt(state.xp_level)}",
        f"{t('player.export.dimension', '维度')}: {_fmt(state.dimension)}",
        f"{t('player.export.game_type', '游戏模式')}: {_fmt(state.game_type)}",
        (
            f"{t('player.export.position', '坐标')}: "
            f"{_fmt(pose.x)}, {_fmt(pose.y)}, {_fmt(pose.z)}"
        ),
        (
            f"{t('player.export.inventory_count', '背包物品数')}: "
            f"{summary.inventory_count}"
        ),
        (
            f"{t('player.export.ender_count', '末影箱物品数')}: "
            f"{summary.ender_count}"
        ),
        (
            f"{t('player.export.equipment_count', '装备数')}: "
            f"{summary.equipment_count}"
        ),
    ]
    if summary.death is not None:
        death = summary.death
        lines.append(
            f"{t('player.export.death', '死亡位置')}: "
            f"{_fmt(death.dimension)} "
            f"({_fmt(death.x)}, {_fmt(death.y)}, {_fmt(death.z)})"
        )
    if summary.issues:
        lines.append(
            f"{t('player.export.issues', '问题')}: {', '.join(summary.issues)}"
        )
    return "\n".join(lines)


def format_export_bundle_text(
    bundle: PlayerExportBundle,
    translate: Optional[Translate] = None,
) -> str:
    """将玩家导出包格式化为纯文本（摘要 + 可选容器列表）。

    Args:
        bundle: 含摘要与容器的导出包。
        translate: 可选 ``(key, default)`` 翻译。
    """
    base = format_player_summary_text(bundle.summary, translate=translate)
    if not bundle.items_included:
        return base
    t = translate or (lambda key, default="", **_kw: default or key)
    sections = [base, "", t("player.export.inventory", "背包:")]
    for item in bundle.containers.inventory:
        sections.append(
            f"  [{item.get('slot')}] {item.get('id')} x{item.get('count')}"
        )
    sections.append(t("player.export.equipment", "装备:"))
    for item in bundle.containers.equipment:
        sections.append(
            f"  [{item.get('slot')}] {item.get('id')} x{item.get('count')}"
        )
    sections.append(t("player.export.ender", "末影箱:"))
    for item in bundle.containers.ender_items:
        sections.append(
            f"  [{item.get('slot')}] {item.get('id')} x{item.get('count')}"
        )
    return "\n".join(sections)


def _fmt(value: object) -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)

import pytest

from app.presenters.world_info_presenter import build_world_info_sections
from core.omni.models import WorldInfo


def _rows(info: WorldInfo, stats=None) -> dict[str, str]:
    return {
        row.label: row.value
        for section in build_world_info_sections(info, stats)
        for row in section.rows
    }


def test_world_info_presenter_builds_grouped_display_model() -> None:
    info = WorldInfo(
        version=3953,
        version_name="1.21",
        version_snapshot=True,
        version_series="main",
        game_type=1,
        difficulty=3,
        hardcore=False,
        allow_commands=True,
        was_modded=False,
        initialized=True,
        seed=-42,
        spawn_x=-10,
        spawn_y=64,
        spawn_z=20,
        time=48000,
        day_time=12500,
        raining=False,
        thundering=True,
        data_packs={
            "enabled": [f"pack-{index}" for index in range(11)],
            "disabled": ["legacy"],
        },
        server_brands=["vanilla", "fabric"],
    )
    stats = {
        "world_path": "C:/saves/demo",
        "player_count": 2,
        "dimension_count": 3,
        "region_count": 4,
    }

    sections = build_world_info_sections(info, stats)
    rows = _rows(info, stats)

    assert [section.title for section in sections] == [
        "📋 基本信息",
        "🌍 世界生成",
        "⏰ 时间与天气",
        "📊 统计信息",
        "📦 数据包",
        "🔧 其他",
    ]
    assert rows["📦 游戏版本"] == "1.21（快照） | 系列: main（ID: 3953）"
    assert rows["🎮 游戏模式"] == "创造模式"
    assert rows["⚔️ 难度"] == "困难"
    assert rows["💀 极限模式"] == "否"
    assert rows["📍 出生点"] == "X: -10  Y: 64  Z: 20"
    assert rows["⏱️ 总游戏时间"] == "48000 刻（约 2 天）"
    assert rows["🌞 当前时段"] == "🌙 夜晚（12500 刻）"
    assert rows["✅ 已启用"].endswith("pack-9...")
    assert rows["🖥️ 服务器品牌"] == "vanilla, fabric"
    assert rows["👥 玩家数"] == "2"


@pytest.mark.parametrize(
    ("ticks", "expected"),
    [
        (0, "☀️ 白天"),
        (6000, "🌅 日落"),
        (12000, "🌙 夜晚"),
        (13000, "🌙 深夜"),
        (18000, "🌄 日出"),
        (23000, "☀️ 黎明"),
        (24000, "☀️ 白天"),
    ],
)
def test_world_info_presenter_formats_day_cycle(ticks: int, expected: str) -> None:
    rows = _rows(WorldInfo(version=0, day_time=ticks))

    assert rows["🌞 当前时段"] == f"{expected}（{ticks % 24000} 刻）"


def test_world_info_presenter_falls_back_for_invalid_timestamp() -> None:
    timestamp = 10**30

    rows = _rows(WorldInfo(version=0, last_played=timestamp))

    assert rows["🕐 最后游玩"] == str(timestamp)

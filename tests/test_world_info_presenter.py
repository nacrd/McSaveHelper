import pytest

from app.presenters.world_info_presenter import build_world_info_sections
from core.omni.models import ModInfo, WorldInfo


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
        was_modded=True,
        initialized=True,
        difficulty_locked=True,
        seed=-42,
        spawn_x=-10,
        spawn_y=64,
        spawn_z=20,
        spawn_angle=90.0,
        generate_features=True,
        bonus_chest=False,
        time=48000,
        day_time=12500,
        raining=False,
        thundering=True,
        data_packs={
            "enabled": [f"pack-{index}" for index in range(11)],
            "disabled": ["legacy"],
        },
        server_brands=["vanilla", "fabric"],
        mods=[
            ModInfo("jei", version="15.3.0", name="Just Enough Items"),
            ModInfo("sodium", version="0.5.8"),
        ],
        mod_loaders=["Fabric Loader 0.15.11"],
        mod_list_complete=True,
        border_center_x=0.0,
        border_center_z=-12.5,
        border_size=10000.0,
        border_warning_blocks=10,
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
        "🧩 模组信息",
        "🧱 世界边界",
        "🔧 其他",
    ]
    assert rows["📦 游戏版本"] == "1.21（快照） | 系列: main（ID: 3953）"
    assert rows["🎮 游戏模式"] == "创造模式"
    assert rows["⚔️ 难度"] == "困难"
    assert rows["💀 极限模式"] == "否"
    assert rows["📍 出生点"] == "X: -10  Y: 64  Z: 20"
    assert rows["🧭 出生朝向"] == "90°"
    assert rows["🏛️ 生成结构"] == "是"
    assert rows["🔒 难度已锁定"] == "是"
    assert rows["⏱️ 总游戏时间"] == "48000 刻（约 2 天）"
    assert rows["🌞 当前时段"] == "🌙 夜晚（12500 刻）"
    assert rows["✅ 已启用"].endswith("pack-9...")
    assert rows["🖥️ 服务器品牌"] == "vanilla, fabric"
    assert rows["👥 玩家数"] == "2"
    assert rows["🧩 是否使用模组"] == "是（存档记录了 2 个模组）"
    assert rows["⚙️ 模组加载器"] == "Fabric Loader 0.15.11"
    assert rows["📚 模组列表"] == (
        "Just Enough Items (jei) · 15.3.0\nsodium · 0.5.8"
    )
    assert rows["🎯 中心坐标"] == "X: 0  Z: -12.5"
    assert rows["↔️ 边界直径"] == "10,000"


def test_world_info_presenter_marks_inferred_mod_list_as_incomplete() -> None:
    rows = _rows(WorldInfo(
        version=0,
        was_modded=True,
        mods=[ModInfo("example")],
        mod_loaders=["Fabric Loader"],
    ))

    assert rows["🧩 是否使用模组"] == "是（至少检测到 1 个，列表可能不完整）"
    assert rows["ℹ️ 清单来源"] == "根据存档数据包标识推断，可能不完整"


def test_world_info_presenter_reports_clean_world_without_mod_list() -> None:
    rows = _rows(WorldInfo(version=0, was_modded=False))

    assert rows["🧩 是否使用模组"] == "否（未检测到模组）"


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

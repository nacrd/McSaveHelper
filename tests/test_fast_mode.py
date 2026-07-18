from pathlib import Path
import pytest

from core.fast_mode import _collect_player_names, _create_dual_player_files
from core.uuid_utils import get_offline_uuid_str


def test_collect_player_names_rejects_manual_name_without_unknown_player(
    tmp_path: Path,
) -> None:
    player_dir = tmp_path / "playerdata"
    player_dir.mkdir()
    old_uuid = "11111111-1111-1111-1111-111111111111"
    player_file = player_dir / f"{old_uuid}.dat"
    player_file.touch()
    logs = []

    with pytest.raises(ValueError, match="必须一对一"):
        _collect_player_names(
            tmp_path,
            {old_uuid: "CachedPlayer"},
            offline_mode=True,
            manual_names=["ManualPlayer"],
            log=lambda message, level: logs.append((message, level)),
        )


def test_collect_player_names_associates_each_unknown_file(tmp_path: Path) -> None:
    player_dir = tmp_path / "playerdata"
    player_dir.mkdir()
    files = []
    for old_uuid in (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ):
        path = player_dir / f"{old_uuid}.dat"
        path.touch()
        files.append(path)

    names, templates = _collect_player_names(
        tmp_path,
        {},
        offline_mode=True,
        manual_names=["Alice", "Bob"],
        log=lambda _message, _level: None,
    )

    assert names == {"Alice", "Bob"}
    assert templates == {"Alice": files[0], "Bob": files[1]}


def test_create_dual_player_files_copies_offline_variant(tmp_path: Path) -> None:
    player_dir = tmp_path / "playerdata"
    player_dir.mkdir()
    template = player_dir / "template.dat"
    template.write_bytes(b"player")
    logs = []

    _create_dual_player_files(
        tmp_path,
        {"Alice"},
        {"Alice": template},
        offline_mode=True,
        log=lambda message, level: logs.append((message, level)),
    )

    offline_file = player_dir / f"{get_offline_uuid_str('Alice')}.dat"
    assert offline_file.read_bytes() == b"player"
    assert any("共生成 1 个" in message for message, _level in logs)


def test_create_dual_player_files_handles_empty_player_set(tmp_path: Path) -> None:
    logs = []

    _create_dual_player_files(
        tmp_path,
        set(),
        {},
        offline_mode=True,
        log=lambda message, level: logs.append((message, level)),
    )

    assert logs == [("未找到任何玩家数据，跳过双UUID生成", "WARN")]
